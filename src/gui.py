"""PyQt6 desktop GUI.

Layout: a search box and controls at the top, a scrollable results list in the
middle, and a status bar at the bottom showing the active Zotero backend and
index size. Indexing (sync) and search both run on background threads so the
window never freezes. On launch the app loads the saved index and kicks off an
incremental sync to pick up any newly added papers.
"""
from __future__ import annotations

import html
import webbrowser

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from .config import Config
from .embedder import Embedder
from .indexer import Indexer
from .search import SearchEngine
from .vector_store import VectorStore


# --------------------------------------------------------------------------- #
# Worker threads
# --------------------------------------------------------------------------- #
class SyncWorker(QThread):
    progress = pyqtSignal(str, float)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, indexer: Indexer):
        super().__init__()
        self.indexer = indexer

    def run(self):
        try:
            result = self.indexer.sync(
                progress=lambda m, f: self.progress.emit(m, f))
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001 - surface any failure to the UI
            self.failed.emit(str(e))


class SearchWorker(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, engine: SearchEngine, query: str, top_k: int,
                 threshold: float):
        super().__init__()
        self.engine = engine
        self.query = query
        self.top_k = top_k
        self.threshold = threshold

    def run(self):
        try:
            hits = self.engine.search(self.query, self.top_k, self.threshold)
            self.done.emit(hits)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# --------------------------------------------------------------------------- #
# Result card
# --------------------------------------------------------------------------- #
class ResultCard(QFrame):
    def __init__(self, hit):
        super().__init__()
        self.hit = hit
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        title = QLabel(html.escape(hit.title or "(untitled)"))
        title.setWordWrap(True)
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title, 1)

        score = QLabel(f"{hit.score:.3f}")
        score.setObjectName("score")
        score.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        top.addWidget(score, 0)
        lay.addLayout(top)

        meta_bits = []
        if hit.authors:
            a = ", ".join(hit.authors[:3]) + (" et al." if len(hit.authors) > 3 else "")
            meta_bits.append(a)
        if hit.year:
            meta_bits.append(hit.year)
        if hit.item_type:
            meta_bits.append(hit.item_type)
        meta_bits.append(f"{hit.matched_chunks} matched passage(s)")
        meta = QLabel(" · ".join(meta_bits))
        meta.setObjectName("meta")
        meta.setWordWrap(True)
        lay.addWidget(meta)

        if hit.abstract:
            abstract = QLabel(html.escape(hit.abstract[:320]
                              + ("…" if len(hit.abstract) > 320 else "")))
            abstract.setWordWrap(True)
            abstract.setObjectName("abstract")
            lay.addWidget(abstract)

        btn = QPushButton("Open in Zotero")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._open)
        btn.setMaximumWidth(160)
        lay.addWidget(btn)

    def _open(self):
        # zotero:// deep-link; fall back to a normal browser open.
        if not QDesktopServices.openUrl(QUrl(self.hit.zotero_uri)):
            webbrowser.open(self.hit.zotero_uri)


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.embedder = Embedder(config)
        self.store = VectorStore(config)
        self.indexer = Indexer(config, embedder=self.embedder, store=self.store)
        self.engine = SearchEngine(config, self.embedder, self.store)
        self.sync_worker: SyncWorker | None = None
        self.search_worker: SearchWorker | None = None

        self.setWindowTitle("Zotero-RAG — Semantic Library Search")
        self.resize(900, 720)
        self._build_ui()
        self._apply_style()

        # Load any saved index, then sync in the background.
        self.indexer.ensure_loaded()
        self._refresh_status()
        self.start_sync()

    # -- UI construction ---------------------------------------------------- #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 10)
        root.setSpacing(10)

        header = QLabel("Zotero-RAG")
        hf = QFont()
        hf.setPointSize(22)
        hf.setBold(True)
        header.setFont(hf)
        root.addWidget(header)

        sub = QLabel("Search your Zotero library by meaning, in English or 日本語.")
        sub.setObjectName("subtitle")
        root.addWidget(sub)

        # Search row
        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(
            "Describe what you're looking for — e.g. 'contrastive self-supervised "
            "learning' / '視覚野の階層的表現'")
        self.search_box.returnPressed.connect(self.run_search)
        self.search_box.setMinimumHeight(38)
        search_row.addWidget(self.search_box, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.setMinimumHeight(38)
        self.search_btn.setDefault(True)
        self.search_btn.clicked.connect(self.run_search)
        search_row.addWidget(self.search_btn)
        root.addLayout(search_row)

        # Controls row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Results:"))
        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(1, 50)
        self.topk_spin.setValue(self.config.top_k)
        controls.addWidget(self.topk_spin)

        controls.addSpacing(16)
        controls.addWidget(QLabel("Min similarity:"))
        self.thresh_spin = QDoubleSpinBox()
        self.thresh_spin.setRange(0.0, 1.0)
        self.thresh_spin.setSingleStep(0.01)
        self.thresh_spin.setDecimals(2)
        self.thresh_spin.setValue(self.config.similarity_threshold)
        controls.addWidget(self.thresh_spin)

        controls.addStretch(1)
        self.sync_btn = QPushButton("Check for new papers")
        self.sync_btn.clicked.connect(self.start_sync)
        controls.addWidget(self.sync_btn)
        root.addLayout(controls)

        # Progress bar (hidden unless syncing)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # Results area
        self.results_area = QScrollArea()
        self.results_area.setWidgetResizable(True)
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(10)
        self.results_area.setWidget(self.results_container)
        root.addWidget(self.results_area, 1)

        # Status bar
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.statusBar().addWidget(self.status)

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f5f6f8; color: #1c1e21; }
            QLabel#subtitle { color: #5a5f66; margin-bottom: 6px; }
            QLineEdit {
                padding: 8px 12px; border: 1px solid #cfd3d8; border-radius: 8px;
                background: #ffffff; font-size: 14px;
            }
            QLineEdit:focus { border: 1px solid #3b6fd4; }
            QPushButton {
                padding: 8px 16px; border-radius: 8px; background: #3b6fd4;
                color: white; font-weight: 600; border: none;
            }
            QPushButton:hover { background: #335fbb; }
            QPushButton:disabled { background: #a9b6cf; }
            QFrame#card {
                background: #ffffff; border: 1px solid #e3e6ea; border-radius: 12px;
            }
            QLabel#meta { color: #6b7178; font-size: 12px; }
            QLabel#abstract { color: #33373c; font-size: 13px; }
            QLabel#score {
                color: #ffffff; background: #2e9e5b; padding: 3px 8px;
                border-radius: 8px; font-weight: 700;
            }
            QLabel#status { color: #5a5f66; }
            QSpinBox, QDoubleSpinBox {
                padding: 4px; border: 1px solid #cfd3d8; border-radius: 6px;
                background: white;
            }
        """)

    # -- status ------------------------------------------------------------- #
    def _refresh_status(self, extra: str = ""):
        backend = self.indexer.client.backend_name()
        msg = (f"Backend: {backend}  ·  Indexed papers: {self.store.n_papers}  "
               f"·  Vectors: {self.store.n_vectors}")
        if extra:
            msg += f"  ·  {extra}"
        self.status.setText(msg)

    # -- sync --------------------------------------------------------------- #
    def start_sync(self):
        if self.sync_worker and self.sync_worker.isRunning():
            return
        self.sync_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.sync_worker = SyncWorker(self.indexer)
        self.sync_worker.progress.connect(self._on_sync_progress)
        self.sync_worker.finished_ok.connect(self._on_sync_done)
        self.sync_worker.failed.connect(self._on_sync_failed)
        self.sync_worker.start()

    def _on_sync_progress(self, msg: str, frac: float):
        self.progress.setValue(int(frac * 100))
        self.status.setText(msg)

    def _on_sync_done(self, result):
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        extra = (f"sync: +{result.added} new, {result.updated} updated, "
                 f"{result.removed} removed  ·  index: {result.index_kind}")
        self._refresh_status(extra)

    def _on_sync_failed(self, err: str):
        self.progress.setVisible(False)
        self.sync_btn.setEnabled(True)
        self.status.setText(f"Sync failed: {err}")

    # -- search ------------------------------------------------------------- #
    def run_search(self):
        query = self.search_box.text().strip()
        if not query:
            return
        if self.store.n_vectors == 0:
            self._show_message("No papers indexed yet. Click "
                               "'Check for new papers' first.")
            return
        # Persist control values to config.
        self.config.top_k = self.topk_spin.value()
        self.config.similarity_threshold = self.thresh_spin.value()
        self.config.save()

        self.search_btn.setEnabled(False)
        self._show_message("Searching …")
        self.search_worker = SearchWorker(
            self.engine, query, self.config.top_k,
            self.config.similarity_threshold)
        self.search_worker.done.connect(self._on_search_done)
        self.search_worker.failed.connect(self._on_search_failed)
        self.search_worker.start()

    def _on_search_done(self, hits):
        self.search_btn.setEnabled(True)
        self._clear_results()
        if not hits:
            self._show_message("No papers above the similarity threshold. "
                               "Try lowering 'Min similarity'.")
            return
        for hit in hits:
            self.results_layout.addWidget(ResultCard(hit))

    def _on_search_failed(self, err: str):
        self.search_btn.setEnabled(True)
        self._show_message(f"Search failed: {err}")

    # -- helpers ------------------------------------------------------------ #
    def _clear_results(self):
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _show_message(self, text: str):
        self._clear_results()
        lbl = QLabel(text)
        lbl.setObjectName("meta")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        self.results_layout.addWidget(lbl)


def run():
    import sys
    app = QApplication(sys.argv)
    app.setApplicationName("Zotero-RAG")
    config = Config.load()
    win = MainWindow(config)
    win.show()
    sys.exit(app.exec())
