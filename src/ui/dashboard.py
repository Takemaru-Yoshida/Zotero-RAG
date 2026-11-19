"""Dashboard: library and fact-check numbers, shortcuts, recent activity."""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .theme import C
from .widgets import (Card, DocCard, PageHeader, button, clear_layout, label,
                      scrollable, verdict_badge)

ACTIONS = [
    ("factcheck", "原稿の引用をチェック →", "AI が書いた文章の引用を原文と照合"),
    ("search", "意味で検索 →", "日本語の質問で英語論文の一節を探す"),
    ("graph", "関連グラフを見る →", "先行研究どうしのつながりを可視化"),
]


class DashboardPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        header = PageHeader("ダッシュボード", "おかえりなさい。今日も確かな引用を。")
        header.add_action(button("＋ 文献を追加", on_click=self.app.add_pdfs))
        outer.addWidget(header)

        body = QWidget()
        self.box = QVBoxLayout(body)
        self.box.setContentsMargins(0, 0, 8, 0)
        self.box.setSpacing(14)
        outer.addWidget(scrollable(body), 1)

        self.stats_row = QHBoxLayout()
        self.box.addLayout(self.stats_row)

        actions = QHBoxLayout()
        for page, title, desc in ACTIONS:
            card = Card(clickable=True)
            card.box.addWidget(label(title, "h2"))
            card.box.addWidget(label(desc, "muted"))
            card.clicked.connect(lambda p=page: self.app.navigate(p))
            actions.addWidget(card)
        self.box.addLayout(actions)

        lower = QHBoxLayout()
        recent = Card()
        top = QHBoxLayout()
        top.addWidget(label("最近追加した文献", "h2"), 1)
        top.addWidget(button("すべて見る", "link",
                             lambda: self.app.navigate("library")))
        recent.box.addLayout(top)
        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(10)
        recent.box.addLayout(self.recent_grid)
        lower.addWidget(recent, 2)

        checks = Card()
        checks.box.addWidget(label("最近のファクトチェック", "h2"))
        self.checks_box = QVBoxLayout()
        checks.box.addLayout(self.checks_box)
        checks.box.addStretch(1)
        lower.addWidget(checks, 1)
        self.box.addLayout(lower)
        self.box.addStretch(1)

    def refresh(self) -> None:
        s = self.app.services
        stats = s.stats()
        clear_layout(self.stats_row)
        for text, value, warn in (
                ("登録文献", stats["documents"], False),
                ("チェック済みの引用", stats["checked"], False),
                ("要確認の引用", stats["needs_review"], True)):
            card = Card()
            num = label(str(value), "stat")
            if warn and value:
                num.setStyleSheet(f"color: {C.refuted};")
            card.box.addWidget(num)
            card.box.addWidget(label(text, "muted"))
            self.stats_row.addWidget(card)

        clear_layout(self.recent_grid)
        docs = s.documents()[:4]
        for i, doc in enumerate(docs):
            card = DocCard(doc)
            card.clicked.connect(lambda k=doc.key: self.app.open_document(k))
            self.recent_grid.addWidget(card, i // 2, i % 2)
        if not docs:
            self.recent_grid.addWidget(label(
                "まだ文献がありません。Zotero を同期するか PDF を追加してください。",
                "muted"), 0, 0)

        clear_layout(self.checks_box)
        runs = s.db.list_factchecks(limit=5)
        for run in runs:
            verdicts = [r.get("verdict", "") for r in run.results]
            bad = sum(1 for v in verdicts if s.needs_review(v))
            worst = next((v for v in ("refuted", "not_found", "partial")
                          if v in verdicts), "supported")
            card = Card(clickable=True, margins=10)
            row = QHBoxLayout()
            row.addWidget(label(run.title, "title", wrap=False), 1)
            row.addWidget(verdict_badge(worst))
            card.box.addLayout(row)
            card.box.addWidget(label(
                f"引用 {len(verdicts)} 件 · 要確認 {bad} 件 · {run.created_at[:16]}",
                "muted"))
            card.clicked.connect(lambda i=run.id: self.app.open_factcheck(i))
            self.checks_box.addWidget(card)
        if not runs:
            self.checks_box.addWidget(label(
                "まだ履歴がありません。「引用ファクトチェック」から原稿を照合できます。",
                "muted"))
