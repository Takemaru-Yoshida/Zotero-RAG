"""Citation fact-check: paste a manuscript, see a verdict per citation."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QProgressBar, QVBoxLayout, QWidget,
)

from .theme import C, SERIF, VERDICTS
from .widgets import (Card, PageHeader, button, clear_layout, label, scrollable,
                      verdict_badge)
from .workers import run_task

ORDER = list(VERDICTS)   # most severe first


def _author_line(result: dict) -> str:
    authors = result.get("authors") or []
    names = f"{authors[0]} ほか" if len(authors) > 2 else ", ".join(authors)
    return f"{names} ({result.get('year', '')})"


class FactCheckPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.results: list[dict] | None = None
        self.filter: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(PageHeader(
            "引用ファクトチェック",
            "原稿を貼り付けると、各引用の主張がライブラリ内の原文に書かれているかを"
            "ローカルの AI（含意判定モデル）が照合します。"))
        columns = QHBoxLayout()
        columns.setSpacing(18)
        outer.addLayout(columns, 1)

        # -- left: manuscript --------------------------------------------- #
        left = Card()
        top = QHBoxLayout()
        top.addWidget(label("原稿", "h2"), 1)
        self.sample_btn = button("サンプルを貼る", "link", self._paste_sample)
        top.addWidget(self.sample_btn)
        left.box.addLayout(top)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(
            "例：Feature-based attention sharpens tuning curves "
            "(Treue & Martinez-Trujillo, 1999).")
        self.text.setStyleSheet(f"font-family: {SERIF}; font-size: 14px;")
        left.box.addWidget(self.text, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        left.box.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.hint = label("(著者, 年) / 著者 (年) 形式の引用に対応", "muted")
        bottom.addWidget(self.hint, 1)
        self.run_btn = button("チェックする", on_click=self._run)
        bottom.addWidget(self.run_btn)
        left.box.addLayout(bottom)
        columns.addWidget(left, 1)

        # -- right: results ----------------------------------------------- #
        right = QVBoxLayout()
        self.tiles = QHBoxLayout()
        right.addLayout(self.tiles)
        body = QWidget()
        self.cards = QVBoxLayout(body)
        self.cards.setContentsMargins(0, 0, 8, 0)
        self.cards.setSpacing(10)
        right.addWidget(scrollable(body), 1)
        columns.addLayout(right, 1)
        self._message("結果はここに表示されます。\n"
                      "まずは「サンプルを貼る」で試してみてください。")

    # -- input -------------------------------------------------------------- #
    def _paste_sample(self) -> None:
        self.sample_btn.setEnabled(False)
        self.hint.setText("ライブラリからサンプル原稿を作成中…")
        run_task(self, self.app.services.sample_manuscript,
                 self._on_sample, self._on_error)

    def _on_sample(self, text: str) -> None:
        self.sample_btn.setEnabled(True)
        self.hint.setText("(著者, 年) / 著者 (年) 形式の引用に対応")
        self.text.setPlainText(text)

    def load_run(self, run_id: int) -> None:
        """Show a past run again (from the dashboard)."""
        for run in self.app.services.db.list_factchecks(limit=1000):
            if run.id == run_id:
                self.text.setPlainText(run.manuscript)
                self.results, self.filter = run.results, None
                self._render()
                return

    def _run(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            return
        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._message("引用文献の本文を検索して照合しています…\n"
                      "（初回は判定モデルのダウンロードに数分かかります）")
        checker = self.app.services.factchecker
        run_task(self,
                 lambda progress: [r.to_dict() for r in checker.check(text, progress)],
                 self._on_done, self._on_error, self._on_progress)

    def _on_progress(self, msg: str, frac: float) -> None:
        self.progress.setValue(int(frac * 100))
        self.hint.setText(msg)

    def _on_error(self, err: str) -> None:
        self.run_btn.setEnabled(True)
        self.sample_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.hint.setText("(著者, 年) / 著者 (年) 形式の引用に対応")
        self._message(f"処理に失敗しました: {err}")

    def _on_done(self, results: list[dict]) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.hint.setText("(著者, 年) / 著者 (年) 形式の引用に対応")
        self.results, self.filter = results, None
        self._render()

    # -- output ------------------------------------------------------------- #
    def _message(self, text: str) -> None:
        clear_layout(self.tiles)
        clear_layout(self.cards)
        self.cards.addWidget(label(text, "muted"))
        self.cards.addStretch(1)

    def _set_filter(self, verdict: str) -> None:
        self.filter = None if self.filter == verdict else verdict
        self._render()

    def _render(self) -> None:
        results = self.results or []
        clear_layout(self.tiles)
        clear_layout(self.cards)
        for verdict in ORDER:
            n = sum(1 for r in results if r["verdict"] == verdict)
            tile = button(f"{n}\n{VERDICTS[verdict][0]}", "tile",
                          lambda v=verdict: self._set_filter(v))
            tile.setCheckable(True)
            tile.setChecked(self.filter == verdict)
            self.tiles.addWidget(tile)
        if not results:
            self.cards.addWidget(label(
                "引用が見つかりませんでした。(著者, 年) 形式の引用を含む文を"
                "入力してください。", "muted"))
        shown = sorted((r for r in results
                        if not self.filter or r["verdict"] == self.filter),
                       key=lambda r: ORDER.index(r["verdict"]))
        for r in shown:
            self.cards.addWidget(self._result_card(r))
        self.cards.addStretch(1)

    def _result_card(self, r: dict) -> Card:
        color = VERDICTS[r["verdict"]][1]
        card = Card()
        card.setStyleSheet(
            f"QFrame#card {{ border-left: 4px solid {color}; }}")
        top = QHBoxLayout()
        top.addWidget(verdict_badge(r["verdict"]))
        top.addStretch(1)
        info = f"({r['citation']})"
        if r.get("key") and r.get("chunk_idx", -1) >= 0:
            info += f" · 一致度 {r['score'] * 100:.0f}%"
        top.addWidget(label(info, "muted", wrap=False))
        card.box.addLayout(top)
        card.box.addWidget(label(r["claim"], "serif", selectable=True))
        if r.get("evidence"):
            evidence = Card(clickable=True, margins=10)
            evidence.setToolTip("クリックすると文献の該当箇所を開きます")
            evidence.box.addWidget(label(
                f"原文の根拠 — {_author_line(r)}, p.{r['page']}", "muted"))
            quote = label(r["evidence"], "serif")
            marker = C.marker_ai if r["verdict"] == "supported" else C.marker
            quote.setStyleSheet(f"background: {marker}; padding: 2px 4px;")
            evidence.box.addWidget(quote)
            evidence.clicked.connect(
                lambda k=r["key"], i=r["chunk_idx"]: self.app.open_document(k, i))
            card.box.addWidget(evidence)
        elif r.get("key"):
            open_btn = button(f"文献を開く — {r.get('title', '')[:50]}", "link",
                              lambda k=r["key"]: self.app.open_document(k))
            card.box.addWidget(open_btn)
        card.box.addWidget(label(r["note"], "muted"))
        return card
