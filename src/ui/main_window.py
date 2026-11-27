"""Main window: sidebar navigation + one page per feature.

The window owns the shared ``Services`` object, runs library sync and PDF
import in the background, and offers the navigation helpers the pages use to
jump to each other (open a paper at a passage, show a paper in the graph …).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QMainWindow,
    QMessageBox, QProgressBar, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import Config
from ..services import Services
from .dashboard import DashboardPage
from .document import DocumentPage
from .factcheck_page import FactCheckPage
from .graph_page import GraphPage
from .library import LibraryPage
from .model_choice import choose_model, needs_model_choice
from .search_page import SearchPage
from .settings_page import SettingsPage
from .theme import apply_theme
from .widgets import button, label
from .workers import run_task

logger = logging.getLogger(__name__)

NAV = [
    ("dashboard", "ダッシュボード"),
    ("library", "ライブラリ"),
    ("search", "意味検索"),
    ("factcheck", "引用ファクトチェック"),
    ("graph", "関連グラフ"),
    ("settings", "設定"),
]


class MainWindow(QMainWindow):
    library_changed = pyqtSignal()   # after sync / PDF import / metadata edit

    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self._syncing = False
        self.setWindowTitle("Zotero-RAG — 文献管理・意味検索・引用ファクトチェック")
        self.resize(1280, 840)
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.stack.setContentsMargins(28, 22, 28, 16)
        root.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self),
            "library": LibraryPage(self),
            "document": DocumentPage(self),
            "search": SearchPage(self),
            "factcheck": FactCheckPage(self),
            "graph": GraphPage(self),
            "settings": SettingsPage(self),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.services.load()
        self.library_changed.connect(self._refresh_current)
        self.navigate("dashboard")
        self._refresh_status()
        self.start_sync()
        # Pick up papers added to Zotero while the app stays open.
        try:
            minutes = float(self.services.config.auto_sync_minutes)
        except (TypeError, ValueError):
            minutes = 0.0
        if minutes > 0:
            self._sync_timer = QTimer(self)
            self._sync_timer.timeout.connect(self.start_sync)
            # At least a minute between checks, at most a day.
            self._sync_timer.start(int(min(max(minutes, 1), 1440) * 60_000))

    # -- layout ------------------------------------------------------------- #
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        box = QVBoxLayout(side)
        box.setContentsMargins(12, 18, 12, 14)
        box.setSpacing(4)
        box.addWidget(label("Zotero-RAG", "logo"))
        box.addWidget(label("確かな引用のための文献管理", "muted"))
        box.addSpacing(14)

        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        for name, text in NAV:
            btn = button(text, "nav", lambda n=name: self.navigate(n))
            btn.setCheckable(True)
            self.nav_group.addButton(btn)
            self.nav_buttons[name] = btn
            box.addWidget(btn)
        box.addStretch(1)

        self.status = label("", "muted")
        box.addWidget(self.status)
        self.status_extra = label("", "muted")
        box.addWidget(self.status_extra)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        box.addWidget(self.progress)
        self.sync_btn = button("新着を確認", "outline", self.start_sync)
        box.addWidget(self.sync_btn)
        return side

    # -- navigation --------------------------------------------------------- #
    def navigate(self, name: str) -> None:
        page = self.pages[name]
        self.stack.setCurrentWidget(page)
        nav_name = "library" if name == "document" else name
        self.nav_buttons[nav_name].setChecked(True)
        if hasattr(page, "refresh"):
            page.refresh()

    def _refresh_current(self) -> None:
        page = self.stack.currentWidget()
        if hasattr(page, "refresh"):
            page.refresh()

    def open_document(self, key: str, chunk_idx: int | None = None) -> None:
        self.pages["document"].show_document(key, chunk_idx)
        self.stack.setCurrentWidget(self.pages["document"])
        self.nav_buttons["library"].setChecked(True)

    def open_graph(self, focus: str | None = None) -> None:
        self.pages["graph"].set_focus(focus)
        self.navigate("graph")

    def open_search(self, query: str = "") -> None:
        self.navigate("search")
        if query:
            self.pages["search"].run(query)

    def open_factcheck(self, run_id: int | None = None) -> None:
        self.navigate("factcheck")
        if run_id is not None:
            self.pages["factcheck"].load_run(run_id)

    # -- status ------------------------------------------------------------- #
    def _refresh_status(self, extra: str = "") -> None:
        s = self.services
        self.status.setText(
            f"文献 {s.store.n_papers} 件 · 一節 {s.store.n_vectors} 件")
        self.status_extra.setText(extra)
        self.status_extra.setVisible(bool(extra))

    # -- sync --------------------------------------------------------------- #
    def start_sync(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.sync_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        stale = self.services.needs_reindex()
        if stale:
            self.status.setText(f"{stale} 件の文献を新しい形式で再インデックスします…")
        elif self.services.store.model_changed:
            self.status.setText(
                "Embedding モデルが変わったため、全文献を再インデックスします…")
        run_task(self, self.services.sync, self._on_sync_done,
                 self._on_sync_failed, self._on_progress)

    def _on_progress(self, msg: str, frac: float) -> None:
        self.progress.setValue(int(frac * 100))
        self.status.setText(msg)
        self.status_extra.setVisible(False)

    def _on_sync_done(self, result) -> None:
        self._syncing = False
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self._refresh_status(
            f"同期: 追加 {result.added} / 更新 {result.updated} / "
            f"削除 {result.removed}")
        if (result.added or result.updated or result.removed
                or result.folders_changed):
            self.library_changed.emit()

    def _on_sync_failed(self, err: str) -> None:
        self._syncing = False
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self._refresh_status(f"同期に失敗: {err}")

    # -- PDF import --------------------------------------------------------- #
    def add_pdfs(self, paths: list[str] | None = None) -> None:
        """Import PDFs chosen in a file dialog (or dropped on the window)."""
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "文献を追加（PDF）", str(Path.home()), "PDF (*.pdf)")
        paths = [p for p in paths if p.lower().endswith(".pdf")]
        if not paths:
            return

        def work(progress):
            added, errors = [], []
            for i, path in enumerate(paths):
                progress(f"取り込み中 [{i + 1}/{len(paths)}] {Path(path).name}",
                         i / len(paths))
                try:
                    added.append(self.services.add_pdf(path))
                except (OSError, ValueError) as e:
                    errors.append(f"{Path(path).name}: {e}")
            return added, errors

        self.progress.setValue(0)
        self.progress.setVisible(True)
        run_task(self, work, self._on_pdfs_added, self._on_import_failed,
                 self._on_progress)

    def _on_pdfs_added(self, result) -> None:
        added, errors = result
        self.progress.setVisible(self._syncing)
        self._refresh_status(f"PDF を {len(added)} 件追加しました")
        self.library_changed.emit()
        if errors:
            QMessageBox.warning(self, "取り込めなかった PDF", "\n".join(errors))
        elif len(added) == 1:
            self.open_document(added[0].key)

    def _on_import_failed(self, err: str) -> None:
        self.progress.setVisible(self._syncing)
        self._refresh_status(f"PDF の取り込みに失敗: {err}")

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        urls = event.mimeData().urls()
        if any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.add_pdfs([u.toLocalFile() for u in event.mimeData().urls()])

    # -- shutdown ----------------------------------------------------------- #
    def closeEvent(self, event) -> None:  # noqa: N802
        tasks = [t for owner in (self, *self.pages.values())
                 for t in owner.__dict__.get("_tasks", [])]
        self.hide()
        if any(t.isRunning() and not t.wait(5000) for t in tasks):
            # A long embedding job is still running; the index is saved at
            # checkpoints, so leave without waiting for the whole sync.
            logger.warning("Exiting while a background task is still running")
            # save() holds this lock while writing, so the exit can never
            # land in the middle of a save.
            with self.services.store._lock:
                os._exit(0)
        super().closeEvent(event)


def run() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("Zotero-RAG")
    apply_theme(app)
    app.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)
    config = Config.load()
    if needs_model_choice(config) and not choose_model(config):
        return          # closed without choosing: asked again next time
    win = MainWindow(Services(config))
    win.show()
    sys.exit(app.exec())
