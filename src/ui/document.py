"""Document viewer: full text or the original PDF with AI markers, in-paper
semantic find, key-sentence list and related papers."""
from __future__ import annotations

import html
import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QStackedWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

from ..highlights import Highlight
from .folder_panel import show_folder_menu
from .pdf_view import PdfMark, PdfView
from .theme import C
from .widgets import (Card, LinkLabel, button, clear_layout, label, scrollable,
                      tag_row)
from .workers import run_task

logger = logging.getLogger(__name__)

_SMALL = f"color:{C.muted_fg}; font-size:11px; font-family:sans-serif;"
TEXT, PDF = "text", "pdf"
# The passage a search hit points at, on a PDF page (the pale tint used in
# the text view would not show on paper white).
PDF_FOCUS = "#d5defa"


def _marked(text: str, sentence: str, color: str) -> str:
    """HTML for ``text`` with ``sentence`` (or all of it) on a marker colour."""
    span = f'<span style="background-color:{color};">%s</span>'
    start = text.find(sentence) if sentence else -1
    if start < 0:
        return span % html.escape(text)
    end = start + len(sentence)
    return (html.escape(text[:start]) + span % html.escape(sentence)
            + html.escape(text[end:]))


def _split(text: str, sep: str) -> list[str]:
    return [part.strip() for part in text.split(sep) if part.strip()]


class MetadataDialog(QDialog):
    """Edit the bibliographic data of an imported PDF."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文献情報を編集")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.title = QLineEdit(doc.title)
        self.authors = QLineEdit("; ".join(doc.authors))
        self.authors.setPlaceholderText("例: Kaiming He; Xiangyu Zhang")
        self.year = QLineEdit(doc.year)
        self.venue = QLineEdit(doc.venue)
        self.doi = QLineEdit(doc.doi)
        self.tags = QLineEdit(", ".join(doc.tags))
        self.abstract = QPlainTextEdit(doc.abstract)
        self.abstract.setFixedHeight(110)
        for text, widget in (("タイトル", self.title),
                             ("著者（; 区切り）", self.authors),
                             ("出版年", self.year), ("掲載誌", self.venue),
                             ("DOI", self.doi), ("タグ（, 区切り）", self.tags),
                             ("要旨", self.abstract)):
            form.addRow(text, widget)
        form.addRow(label("引用ファクトチェックは「著者の姓 + 出版年」で文献を"
                          "特定するため、著者と出版年を正しく入力してください。",
                          "muted"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def fields(self) -> dict:
        return {
            "title": self.title.text().strip() or "(untitled)",
            "authors": _split(self.authors.text(), ";"),
            "year": self.year.text().strip(), "venue": self.venue.text().strip(),
            "doi": self.doi.text().strip(), "tags": _split(self.tags.text(), ","),
            "abstract": self.abstract.toPlainText().strip(),
        }


class DocumentPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.key: str | None = None
        self.doc = None
        self.focus: int | None = None
        self.chunks = []
        self.key_marks: list[Highlight] = []
        self.query_marks: list[Highlight] = []
        self.query = ""
        self.mode = PDF if app.services.config.document_view == PDF else TEXT
        self.pdf_on = False     # the PDF is what is on screen right now

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(button("← ライブラリ", "link",
                              lambda: self.app.navigate("library")))
        self.tags_box = QVBoxLayout()
        left.addLayout(self.tags_box)
        self.title = label("", "docTitle", selectable=True)
        left.addWidget(self.title)
        self.meta = label("", "muted")
        left.addWidget(self.meta)
        self.buttons = QHBoxLayout()
        left.addLayout(self.buttons)
        self.abstract = label("", "abstract", selectable=True)
        left.addWidget(self.abstract)
        modes = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        for mode, text in ((TEXT, "テキスト"), (PDF, "PDF")):
            btn = button(text, "chip", lambda m=mode: self._set_mode(m))
            btn.setCheckable(True)
            self.mode_group.addButton(btn)
            self.mode_buttons[mode] = btn
            modes.addWidget(btn)
        self.mode_note = label("", "muted")
        modes.addWidget(self.mode_note, 1)
        left.addLayout(modes)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.pdf = PdfView()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.body)
        self.stack.addWidget(self.pdf)
        left.addWidget(self.stack, 1)
        root.addLayout(left, 1)

        side = QWidget()
        self.side = QVBoxLayout(side)
        self.side.setContentsMargins(0, 0, 8, 0)
        self.side.setSpacing(12)
        side_area = scrollable(side)
        side_area.setFixedWidth(312)
        side_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(side_area)

        find = Card()
        find.box.addWidget(label("探したい文を探す", "h2"))
        row = QHBoxLayout()
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("例：比較に使う指標")
        self.find_box.returnPressed.connect(self._find)
        row.addWidget(self.find_box, 1)
        self.find_btn = button("探す", on_click=self._find)
        row.addWidget(self.find_btn)
        find.box.addLayout(row)
        self.find_status = label(
            "意味が近い文に黄色のマーカーが付きます。日本語でも検索できます。", "muted")
        find.box.addWidget(self.find_status)
        self.clear_btn = button("マーカーを消す", "link", self._clear_find)
        self.clear_btn.setVisible(False)
        find.box.addWidget(self.clear_btn)
        self.ai_toggle = QCheckBox("AI 重要文マーカー")
        self.ai_toggle.setChecked(self.app.services.config.auto_mark)
        self.ai_toggle.toggled.connect(
            lambda _on: self._render_body(keep_scroll=True))
        find.box.addWidget(self.ai_toggle)
        self.side.addWidget(find)

        keys = Card()
        keys.box.addWidget(label("AI が選んだ重要文", "h2"))
        self.keys_box = QVBoxLayout()
        keys.box.addLayout(self.keys_box)
        self.side.addWidget(keys)

        related = Card()
        related.box.addWidget(label("関連文献", "h2"))
        self.related_box = QVBoxLayout()
        related.box.addLayout(self.related_box)
        related.box.addWidget(button(
            "グラフで見る", "outline", lambda: self.app.open_graph(self.key)))
        self.side.addWidget(related)
        self.side.addStretch(1)

    # -- loading ------------------------------------------------------------ #
    def refresh(self) -> None:
        if self.key:
            self.show_document(self.key, self.focus)

    def show_document(self, key: str, chunk_idx: int | None = None) -> None:
        s = self.app.services
        doc = s.document(key)
        if doc is None:
            self.key = None
            self.app.navigate("library")
            return
        if key != self.key:
            self.query_marks, self.query = [], ""
            self.find_box.clear()
            self.clear_btn.setVisible(False)
        self.key, self.doc, self.focus = key, doc, chunk_idx
        self.chunks = s.db.get_chunks(key)
        self.key_marks = []

        clear_layout(self.tags_box)
        if doc.tags:
            self.tags_box.addWidget(tag_row(doc.tags, limit=8))
        self.title.setText(doc.title)
        bits = [doc.author_line, doc.venue,
                f"{doc.pages} ページ" if doc.pages else "",
                f"一節 {len(self.chunks)} 件"]
        self.meta.setText(" · ".join(b for b in bits if b))
        self.abstract.setVisible(bool(doc.abstract))
        self.abstract.setText(f"要旨　{doc.abstract}")
        self._build_buttons()
        self._apply_mode()
        self._render_body()
        self._load_side(key)

    def _build_buttons(self) -> None:
        clear_layout(self.buttons)
        doc = self.doc
        star = "★ お気に入り" if doc.starred else "☆ お気に入り"
        self.buttons.addWidget(button(star, "outline", self._toggle_star))
        self.buttons.addWidget(button("フォルダ", "outline", self._folders))
        if doc.doi:
            self.buttons.addWidget(button("DOI", "outline", lambda: self._open(
                QUrl(f"https://doi.org/{doc.doi}"))))
        if not doc.is_local:
            self.buttons.addWidget(button("Zotero で開く", "outline",
                                          lambda: self._open(QUrl(doc.zotero_uri))))
        if doc.pdf_path and Path(doc.pdf_path).exists():
            self.buttons.addWidget(button("PDF を開く", "outline", lambda: self._open(
                QUrl.fromLocalFile(doc.pdf_path))))
        if doc.is_local:
            self.buttons.addWidget(button("情報を編集", "outline", self._edit))
            self.buttons.addWidget(button("削除", "outline", self._delete))
        self.buttons.addStretch(1)

    def _load_side(self, key: str) -> None:
        s = self.app.services
        clear_layout(self.keys_box)
        self.keys_box.addWidget(label("重要文を抽出中…", "muted"))
        run_task(self, lambda: (key, s.highlighter.key_sentences(key)),
                 self._on_key_sentences, self._on_side_error)
        clear_layout(self.related_box)
        for doc in s.related(key, 4):
            self.related_box.addWidget(LinkLabel(
                doc.title, lambda k=doc.key: self.app.open_document(k)))
            self.related_box.addWidget(label(doc.author_line, "muted"))

    def _on_key_sentences(self, result) -> None:
        key, marks = result
        if key != self.key:
            return   # the user already opened another paper
        self.key_marks = marks
        clear_layout(self.keys_box)
        for m in marks:
            text = m.sentence if len(m.sentence) <= 90 else m.sentence[:90] + "…"
            entry = Card(clickable=True, margins=8)
            entry.setToolTip(m.reason)
            entry.box.addWidget(label(text, "muted"))
            entry.clicked.connect(lambda i=m.chunk_idx: self._scroll_to(i))
            self.keys_box.addWidget(entry)
        if not marks:
            self.keys_box.addWidget(label("重要文を抽出できませんでした。", "muted"))
        self._render_body(keep_scroll=self.focus is None)

    def _on_side_error(self, err: str) -> None:
        clear_layout(self.keys_box)
        self.keys_box.addWidget(label(f"重要文の抽出に失敗: {err}", "muted"))

    # -- body --------------------------------------------------------------- #
    def _render_body(self, keep_scroll: bool = False) -> None:
        bar = self.body.verticalScrollBar()
        position = bar.value()
        ai = ({m.chunk_idx: m for m in self.key_marks}
              if self.ai_toggle.isChecked() else {})
        found = {m.chunk_idx: m for m in self.query_marks}
        parts: list[str] = []
        for c in self.chunks:
            q, k = found.get(c.idx), ai.get(c.idx)
            if q:
                text = _marked(c.text, q.sentence, C.marker)
                note = f"🔍 「{html.escape(self.query)}」に一致 · {q.reason}"
            elif k:
                text = _marked(c.text, k.sentence, C.marker_ai)
                note = f"✦ {html.escape(k.reason)}"
            else:
                text, note = html.escape(c.text), ""
            style = "margin:0 0 14px 0; line-height:160%;"
            if c.idx == self.focus:
                style += f" background-color:{C.focus};"
            note_html = f'<br><span style="{_SMALL}">{note}</span>' if note else ""
            parts.append(
                f'<a name="c{c.idx}"></a><p style="{style}">{text} '
                f'<span style="{_SMALL}">p.{c.page}</span>{note_html}</p>')
        if not parts:
            parts.append(f'<p style="{_SMALL}">本文がありません。'
                         "「新着を確認」で再インデックスしてください。</p>")
        self.body.setHtml("".join(parts))
        if self.pdf_on:
            self._mark_pdf(ai, found)
        if keep_scroll:
            bar.setValue(position)
        elif self.focus is not None:
            self._scroll_to(self.focus)

    def _scroll_to(self, chunk_idx: int) -> None:
        if self.pdf_on:
            page = next((c.page for c in self.chunks if c.idx == chunk_idx), 1)
            self.pdf.scroll_to(chunk_idx, page)
        else:
            self.body.scrollToAnchor(f"c{chunk_idx}")

    # -- text / PDF --------------------------------------------------------- #
    def _pdf_path(self) -> str:
        path = self.doc.pdf_path if self.doc else ""
        return path if path and Path(path).exists() else ""

    def _set_mode(self, mode: str) -> None:
        if mode == self.mode and self.pdf_on == (mode == PDF):
            return      # already showing it
        self.mode = mode
        config = self.app.services.config
        if config.document_view != mode:
            config.document_view = mode
            try:
                config.save()
            except OSError as e:
                logger.warning("Could not save the view setting: %s", e)
        self._apply_mode()
        self._render_body()
        marks = self.query_marks or (
            self.key_marks if self.ai_toggle.isChecked() else [])
        if self.focus is None and marks and self.pdf_on:
            self._scroll_to(marks[0].chunk_idx)

    def _apply_mode(self) -> None:
        """Show the PDF when it is asked for and can be opened, else the text."""
        path = self._pdf_path()
        self.mode_buttons[PDF].setEnabled(bool(path))
        self.mode_buttons[PDF].setToolTip(
            "" if path else "この文献には PDF がありません")
        self.pdf_on = self.mode == PDF and bool(path) and self.pdf.load(path)
        note = ""
        if self.mode == PDF and not self.pdf_on:
            note = ("PDF を開けないため、テキストで表示しています。" if path
                    else "PDF がないため、テキストで表示しています。")
        if not self.pdf_on:
            self.pdf.close_pdf()
        self.mode_note.setText(note)
        self.mode_buttons[PDF if self.pdf_on else TEXT].setChecked(True)
        self.stack.setCurrentWidget(self.pdf if self.pdf_on else self.body)

    def _mark_pdf(self, ai: dict, found: dict) -> None:
        """Draw on the PDF what the text view marks."""
        marks: list[PdfMark] = []
        for c in self.chunks:
            q, k = found.get(c.idx), ai.get(c.idx)
            if q:
                marks.append(PdfMark(c.idx, c.page, q.sentence or c.text, C.marker))
            elif k:
                marks.append(PdfMark(c.idx, c.page, k.sentence or c.text,
                                     C.marker_ai))
            elif c.idx == self.focus:
                marks.append(PdfMark(c.idx, c.page, c.text, PDF_FOCUS))
        missing = self.pdf.set_marks(marks)
        self.mode_note.setText(
            f"{missing} 件のマーカーは PDF 上の位置を特定できませんでした"
            "（テキスト表示で確認できます）。" if missing else "")

    # -- find in paper ------------------------------------------------------ #
    def _find(self) -> None:
        query = self.find_box.text().strip()
        if not query or not self.key:
            return
        key = self.key
        self.find_btn.setEnabled(False)
        self.find_status.setText("検索中…")
        run_task(self,
                 lambda: (key, query, self.app.services.highlighter.find(key, query)),
                 self._on_found, self._on_find_error)

    def _on_found(self, result) -> None:
        key, query, marks = result
        self.find_btn.setEnabled(True)
        if key != self.key:
            return
        self.query, self.query_marks = query, marks
        self.clear_btn.setVisible(bool(marks))
        self.find_status.setText(
            f"{len(marks)} 件の一節にマーカーを付けました。" if marks
            else "該当する一節が見つかりませんでした。")
        self._render_body(keep_scroll=True)
        if marks:
            self._scroll_to(marks[0].chunk_idx)

    def _on_find_error(self, err: str) -> None:
        self.find_btn.setEnabled(True)
        self.find_status.setText(f"検索に失敗: {err}")

    def _clear_find(self) -> None:
        self.query_marks, self.query = [], ""
        self.clear_btn.setVisible(False)
        self.find_status.setText("マーカーを消しました。")
        self._render_body(keep_scroll=True)

    # -- actions ------------------------------------------------------------ #
    def _open(self, url: QUrl) -> None:
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(self, "開けませんでした", url.toString())

    def _folders(self) -> None:
        show_folder_menu(self, self.app.services, self.key, QCursor.pos(),
                         lambda: None)

    def _toggle_star(self) -> None:
        self.app.services.toggle_star(self.key)
        self.doc = self.app.services.document(self.key)
        self._build_buttons()

    def _edit(self) -> None:
        dialog = MetadataDialog(self.doc, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.app.services.update_local(self.key, dialog.fields())
            self.app.library_changed.emit()

    def _delete(self) -> None:
        answer = QMessageBox.question(
            self, "文献を削除",
            f"「{self.doc.title}」をライブラリから削除しますか？\n"
            "アプリ内にコピーした PDF とインデックスが削除されます"
            "（元の PDF ファイルは残ります）。")
        if answer != QMessageBox.StandardButton.Yes:
            return
        key, self.key = self.key, None
        self.app.services.remove_local(key)
        self.app.navigate("library")
