"""Library: every indexed paper, filterable by text, tag and star."""
from __future__ import annotations

from collections import Counter

from PyQt6.QtWidgets import QGridLayout, QLineEdit, QVBoxLayout, QWidget

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

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("ライブラリ")
        self.header.add_action(button("＋ 文献を追加", on_click=self.app.add_pdfs))
        outer.addWidget(self.header)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("タイトル・著者・掲載誌で絞り込み")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _text: self._render())
        outer.addWidget(self.filter)

        chips = QWidget()
        self.chips = FlowLayout()
        chips.setLayout(self.chips)
        outer.addWidget(chips)

        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 4, 8, 0)
        self.grid.setSpacing(10)
        outer.addWidget(scrollable(body), 1)

    def refresh(self) -> None:
        self.docs = self.app.services.documents()
        self.header.desc.setText(
            f"{len(self.docs)} 件の文献（Zotero と追加した PDF）。"
            "PDF をウィンドウにドロップしても追加できます。")
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

    def _render(self) -> None:
        clear_layout(self.grid)
        query = self.filter.text().strip().lower()
        shown = [d for d in self.docs if self._matches(d, query)]
        for i, doc in enumerate(shown):
            card = DocCard(doc)
            card.clicked.connect(lambda k=doc.key: self.app.open_document(k))
            self.grid.addWidget(card, i // 2, i % 2)
        if not shown:
            self.grid.addWidget(label("該当する文献がありません", "muted"), 0, 0)
        self.grid.setRowStretch(len(shown) // 2 + 1, 1)
