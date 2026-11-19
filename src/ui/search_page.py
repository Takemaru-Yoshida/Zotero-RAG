"""Semantic search: passages of the whole library ranked by meaning (RAG)."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDoubleSpinBox, QHBoxLayout, QLineEdit, QProgressBar, QSpinBox,
    QVBoxLayout, QWidget,
)

from .widgets import (Card, FlowLayout, PageHeader, button, clear_layout,
                      label, scrollable)
from .workers import run_task

EXAMPLES = ["注意は脳の表象をどう変えるか", "モデルと脳を比較する方法",
            "深いネットワークを学習させる工夫", "解析の循環性を避けるには"]


def _author_line(hit) -> str:
    names = (f"{hit.authors[0]} ほか" if len(hit.authors) > 2
             else ", ".join(hit.authors))
    return f"{names} ({hit.year})" if hit.year else names


class SearchPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._request = 0   # ignore results of superseded searches
        config = app.services.config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(PageHeader(
            "意味検索",
            "キーワードではなく「意味」で、ライブラリ内の全文献から関連する一節を"
            "探します（RAG）。"))

        row = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setPlaceholderText("知りたいことを文章で入力（日本語・英語）")
        self.box.setMinimumHeight(40)
        self.box.returnPressed.connect(lambda: self.run(self.box.text()))
        row.addWidget(self.box, 1)
        self.btn = button("検索", on_click=lambda: self.run(self.box.text()))
        self.btn.setMinimumHeight(40)
        row.addWidget(self.btn)
        outer.addLayout(row)

        chips = QWidget()
        flow = FlowLayout()
        chips.setLayout(flow)
        for example in EXAMPLES:
            flow.addWidget(button(example, "chip", lambda e=example: self.run(e)))
        outer.addWidget(chips)

        controls = QHBoxLayout()
        controls.addWidget(label("表示件数", "muted", wrap=False))
        self.limit = QSpinBox()
        self.limit.setRange(1, 50)
        self.limit.setValue(config.top_k)
        controls.addWidget(self.limit)
        controls.addSpacing(14)
        controls.addWidget(label("最小類似度", "muted", wrap=False))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.0, 1.0)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setValue(config.similarity_threshold)
        controls.addWidget(self.threshold)
        controls.addStretch(1)
        outer.addLayout(controls)

        body = QWidget()
        self.results = QVBoxLayout(body)
        self.results.setContentsMargins(0, 6, 8, 0)
        self.results.setSpacing(10)
        outer.addWidget(scrollable(body), 1)
        self._message("質問を入力すると、意味の近い一節が類似度順に表示されます。")

    def _message(self, text: str) -> None:
        clear_layout(self.results)
        self.results.addWidget(label(text, "muted"))
        self.results.addStretch(1)

    def run(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        s = self.app.services
        self.box.setText(query)
        if s.store.n_vectors == 0:
            self._message("まだ文献がインデックスされていません。"
                          "「新着を確認」を実行してください。")
            return
        s.config.top_k = self.limit.value()
        s.config.similarity_threshold = self.threshold.value()
        s.config.save()
        self._request += 1
        request = self._request
        self.btn.setEnabled(False)
        self._message("ベクトル検索中…")
        run_task(self, lambda: (request, s.engine.search_passages(query)),
                 self._on_done, self._on_error)

    def _on_error(self, err: str) -> None:
        self.btn.setEnabled(True)
        self._message(f"検索に失敗しました: {err}")

    def _on_done(self, result) -> None:
        request, hits = result
        if request != self._request:
            return
        self.btn.setEnabled(True)
        if not hits:
            self._message("該当する一節が見つかりませんでした。"
                          "「最小類似度」を下げると候補が増えます。")
            return
        clear_layout(self.results)
        self.results.addWidget(label(f"{len(hits)} 件の一節が見つかりました", "muted"))
        for hit in hits:
            card = Card(clickable=True)
            top = QHBoxLayout()
            top.addWidget(label(f"{hit.score * 100:.0f}%", "h2", wrap=False))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(hit.score * 100))
            bar.setFixedWidth(140)
            top.addWidget(bar)
            top.addStretch(1)
            top.addWidget(label(f"p.{hit.page}", "muted", wrap=False))
            card.box.addLayout(top)
            card.box.addWidget(label(hit.text, "serif"))
            card.box.addWidget(label(f"{hit.title} — {_author_line(hit)}", "muted"))
            card.clicked.connect(
                lambda k=hit.key, i=hit.chunk_idx: self.app.open_document(k, i))
            self.results.addWidget(card)
        self.results.addStretch(1)
