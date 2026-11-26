"""Folder list of the library page, and the menu that files a paper.

Zotero collections are shown as a read-only tree (they are edited in Zotero
and mirrored on every sync); the user's own folders can be created, renamed
and deleted here.
"""
from __future__ import annotations

from typing import Callable, Sequence

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QInputDialog, QMenu, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..folders import filed, members, tree
from ..library_db import APP, ZOTERO, FolderRow
from .widgets import button

ALL = "all"
UNFILED = "unfiled"
_ID = Qt.ItemDataRole.UserRole


def ask_folder_name(parent: QWidget, title: str, current: str = "") -> str:
    """Ask for a folder name; "" when the dialog was cancelled."""
    name, ok = QInputDialog.getText(parent, title, "フォルダ名", text=current)
    return name.strip() if ok else ""


def create_folder(parent: QWidget, services) -> int | None:
    """Ask for a name and create the folder; ``None`` if nothing was created."""
    name = ask_folder_name(parent, "新しいフォルダ")
    if not name:
        return None
    try:
        return services.add_folder(name)
    except ValueError as e:
        QMessageBox.warning(parent, "フォルダを作成できません", str(e))
        return None


def show_folder_menu(parent: QWidget, services, key: str, pos,
                     on_change: Callable[[], None]) -> None:
    """Pop up the menu that puts paper ``key`` into the user's folders.

    The menu opens after the calling handler has returned: a background sync
    that ends while it is open rebuilds the page, and the card or button that
    was clicked must not be deleted while its own handler is still running.
    ``parent`` therefore has to be a page, not such a short-lived widget.
    """
    QTimer.singleShot(
        0, parent, lambda: _folder_menu(parent, services, key, pos, on_change))


def _folder_menu(parent: QWidget, services, key: str, pos,
                 on_change: Callable[[], None]) -> None:
    menu = QMenu(parent)
    own = [f for f in services.folders() if f.source == APP]
    for f in own:
        action = menu.addAction(f.name)
        action.setCheckable(True)
        action.setChecked(key in f.keys)
        action.setData(f)
    if own:
        menu.addSeparator()
    new = menu.addAction("新しいフォルダに追加…")
    chosen = menu.exec(pos)
    if chosen is None:
        return
    if chosen is new:
        folder_id = create_folder(parent, services)
        if folder_id is None:
            return
        services.set_in_folder(folder_id, key, True)
    else:
        f = chosen.data()
        services.set_in_folder(int(f.ref), key, key not in f.keys)
    on_change()


class FolderPanel(QWidget):
    selected = pyqtSignal()     # another folder was picked
    changed = pyqtSignal()      # a folder was created, renamed or deleted

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.current = ALL
        self.setFixedWidth(236)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setIndentation(14)
        self.tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.currentItemChanged.connect(self._on_current)
        box.addWidget(self.tree, 1)
        box.addWidget(button("＋ 新しいフォルダ", "outline", self._create))

    # -- content ------------------------------------------------------------ #
    def refresh(self, folders: Sequence[FolderRow], doc_keys: set[str]) -> None:
        """Rebuild the list; counts only papers that are in the library."""
        ids = {f.id for f in folders}
        if self.current not in (ALL, UNFILED, *ids):
            self.current = ALL
        self.tree.blockSignals(True)
        self.tree.clear()
        self._row(None, "すべての文献", len(doc_keys), ALL)
        self._row(None, "未分類", len(doc_keys - filed(folders)), UNFILED)
        for source, title in ((ZOTERO, "Zotero コレクション"),
                              (APP, "マイフォルダ")):
            group = [f for f in folders if f.source == source]
            if not group:
                continue
            parents: list[QTreeWidgetItem] = [self._heading(title)]
            for f, depth in tree(group):
                del parents[depth + 1:]
                count = len(members(group, f.id) & doc_keys)
                parents.append(self._row(parents[depth], f.name, count, f.id))
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _heading(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, [title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setForeground(0, self.tree.palette().placeholderText())
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        return item

    def _row(self, parent: QTreeWidgetItem | None, name: str, count: int,
             folder_id: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent or self.tree, [f"{name}  ({count})"])
        item.setData(0, _ID, folder_id)
        item.setToolTip(0, name)
        if folder_id == self.current:
            self.tree.setCurrentItem(item)
        return item

    def _on_current(self, item: QTreeWidgetItem | None, _previous) -> None:
        folder_id = item.data(0, _ID) if item else None
        if folder_id and folder_id != self.current:
            self.current = folder_id
            self.selected.emit()

    # -- the user's own folders --------------------------------------------- #
    def _create(self) -> None:
        folder_id = create_folder(self, self.app.services)
        if folder_id is not None:
            self.current = f"{APP}:{folder_id}"
            self.changed.emit()

    def _context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        folder_id = (item.data(0, _ID) if item else None) or ""
        source, _, ref = folder_id.partition(":")
        if source != APP:
            return      # Zotero collections are edited in Zotero
        name = item.toolTip(0)
        menu = QMenu(self)
        rename = menu.addAction("名前を変更…")
        delete = menu.addAction("フォルダを削除")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is rename:
            self._rename(int(ref), name)
        elif chosen is delete:
            self._delete(int(ref), name)

    def _rename(self, folder_id: int, name: str) -> None:
        new = ask_folder_name(self, "フォルダ名を変更", name)
        if not new or new == name:
            return
        try:
            self.app.services.rename_folder(folder_id, new)
        except ValueError as e:
            QMessageBox.warning(self, "名前を変更できません", str(e))
            return
        self.changed.emit()

    def _delete(self, folder_id: int, name: str) -> None:
        answer = QMessageBox.question(
            self, "フォルダを削除",
            f"フォルダ「{name}」を削除しますか？\n中の文献はライブラリに残ります。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.app.services.delete_folder(folder_id)
        self.changed.emit()
