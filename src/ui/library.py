"""Library: every indexed paper, filterable by folder, text, tag and star."""
from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout,
                             QWidget)

from ..folders import filed, members
from .folder_panel import ALL, UNFILED, FolderPanel, show_folder_menu
from .widgets import (DocCard, FlowLayout, PageHeader, button, clear_layout,
                      label, scrollable)

MAX_TAG_CHIPS = 24
STARRED = "★ お気に入り"


class LibraryPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.tag: str | None = None
        self.docs = []
        self.folders = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("ライブラリ")
        self.header.add_action(button("＋ 文献を追加", on_click=self.app.add_pdfs))
        outer.addWidget(self.header)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        outer.addLayout(columns, 1)
        self.panel = FolderPanel(app)
        self.panel.selected.connect(self._render)
        self.panel.changed.connect(self.refresh)
        columns.addWidget(self.panel)
        right = QVBoxLayout()
        columns.addLayout(right, 1)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("タイトル・著者・掲載誌で絞り込み")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _text: self._render())
        right.addWidget(self.filter)

        chips = QWidget()
        self.chips = FlowLayout()
        chips.setLayout(self.chips)
        right.addWidget(chips)

        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 4, 8, 0)
        self.grid.setSpacing(10)
        right.addWidget(scrollable(body), 1)

    def refresh(self) -> None:
        self.docs = self.app.services.documents()
        self.header.desc.setText(
            f"{len(self.docs)} 件の文献（Zotero と追加した PDF）。"
            "PDF をウィンドウにドロップしても追加できます。"
            "文献を右クリックするとフォルダに入れられます。")
        self.folders = self.app.services.folders()
        self.panel.refresh(self.folders, {d.key for d in self.docs})
        counts = Counter(t for d in self.docs for t in d.tags)
        tags = [t for t, _ in counts.most_common(MAX_TAG_CHIPS)]
        if self.tag not in (None, STARRED, *tags):
            self.tag = None
        clear_layout(self.chips)
        for value, text in [(None, "すべて"), (STARRED, STARRED),
                            *((t, t) for t in tags)]:
            chip = button(text, "chip", lambda v=value: self._set_tag(v))
            chip.setCheckable(True)
            chip.setChecked(value == self.tag)
            self.chips.addWidget(chip)
        self._render()

    def _set_tag(self, tag: str | None) -> None:
        self.tag = tag
        self.refresh()

    def _matches(self, doc, query: str) -> bool:
        if self.tag == STARRED and not doc.starred:
            return False
        if self.tag not in (None, STARRED) and self.tag not in doc.tags:
            return False
        haystack = f"{doc.title} {' '.join(doc.authors)} {doc.venue}".lower()
        return query in haystack

    def _in_folder(self) -> set[str] | None:
        """Keys of the papers in the selected folder (``None`` = no filter)."""
        current = self.panel.current
        if current == ALL:
            return None
        if current == UNFILED:
            return {d.key for d in self.docs} - filed(self.folders)
        return members(self.folders, current)

    def _folder_menu(self, card: DocCard, pos) -> None:
        show_folder_menu(self, self.app.services, card.doc.key,
                         card.mapToGlobal(pos), self.refresh)

    def _render(self) -> None:
        clear_layout(self.grid)
        query = self.filter.text().strip().lower()
        keys = self._in_folder()
        shown = [d for d in self.docs if (keys is None or d.key in keys)
                 and self._matches(d, query)]
        for i, doc in enumerate(shown):
            card = DocCard(doc)
            card.clicked.connect(lambda k=doc.key: self.app.open_document(k))
            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            card.customContextMenuRequested.connect(
                lambda pos, c=card: self._folder_menu(c, pos))
            self.grid.addWidget(card, i // 2, i % 2)
        if not shown:
            self.grid.addWidget(label("該当する文献がありません", "muted"), 0, 0)
        self.grid.setRowStretch(len(shown) // 2 + 1, 1)
