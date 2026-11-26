"""The original PDF of a paper with the markers drawn on its pages.

Pages are rendered with QtPdf at the width of the view, only around the part
that is visible. A marker is a sentence of the extracted text; its place on
the page is looked up in the page's text layer (see ``pdf_locate``), so a
scanned PDF without text layer is shown without markers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..pdf_locate import PageText, letters_of, locate
from .theme import C

MARGIN = 8          # around the pages
GAP = 12            # between pages
MIN_WIDTH = 320
# A passage is looked for on its own page first, then on the pages around it
# (the page count of the extracted text can be off by a cover page).
NEARBY = (0, 1, -1, 2, -2)
PROBE = 16          # characters compared to check where a selection begins


@dataclass(frozen=True)
class PdfMark:
    chunk_idx: int
    page: int           # page of the passage in the extracted text (1-based)
    text: str           # sentence to mark
    color: str


class PdfView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Always there: a bar that comes and goes changes the page width,
        # which changes the page height, which brings the bar back ...
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        holder = QWidget()
        self.column = QVBoxLayout(holder)
        self.column.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.column.setSpacing(GAP)
        self.column.addStretch(1)
        self.setWidget(holder)

        self.pdf = QPdfDocument(self)
        self.path = ""
        self._stamp = 0.0       # modification time of the loaded file
        self.pages: list[QLabel] = []
        self._tops: list[int] = []              # y of every page in the column
        self._rendered: set[int] = set()
        self._texts: dict[int, PageText] = {}
        self._raw: dict[int, str] = {}          # page text as QtPdf returns it
        self._shapes: dict[int, list[tuple[QPainterPath, str]]] = {}
        self._where: dict[int, tuple[int, float]] = {}   # chunk -> page, y (pt)
        self._goto: int | None = None

        self.verticalScrollBar().valueChanged.connect(self._render_visible)
        self._relayout = QTimer(self)
        self._relayout.setSingleShot(True)
        self._relayout.setInterval(120)
        self._relayout.timeout.connect(self._layout_pages)

    # -- document ----------------------------------------------------------- #
    def load(self, path: str) -> bool:
        """Show another PDF; ``False`` when it cannot be opened."""
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = 0.0
        # The same file again, unless a sync replaced it in the meantime.
        if path == self.path and stamp == self._stamp and self.pages:
            return True
        self.close_pdf()
        if self.pdf.load(path) != QPdfDocument.Error.None_:
            return False
        self.path, self._stamp = path, stamp
        for _ in range(self.pdf.pageCount()):
            page = QLabel()
            self.pages.append(page)
            self.column.insertWidget(self.column.count() - 1, page)
        self.verticalScrollBar().setValue(0)
        self._layout_pages()
        return bool(self.pages)

    def close_pdf(self) -> None:
        for page in self.pages:
            page.setParent(None)
            page.deleteLater()
        self.pages = []
        self._tops = []
        self._rendered.clear()
        self._texts.clear()
        self._raw.clear()
        self._shapes.clear()
        self._where.clear()
        self.path = ""
        self.pdf.close()

    # -- markers ------------------------------------------------------------ #
    def set_marks(self, marks: Sequence[PdfMark]) -> int:
        """Draw these markers; returns how many could not be found in the PDF."""
        self._shapes.clear()
        self._where.clear()
        missing = 0
        for mark in marks:
            if not self._place(mark):
                missing += 1
        self._rendered.clear()
        self._render_visible()
        return missing

    def _place(self, mark: PdfMark) -> bool:
        for offset in NEARBY:
            page = mark.page - 1 + offset
            if not 0 <= page < len(self.pages):
                continue
            polygons = [polygon
                        for span in locate(self._text(page), mark.text)
                        for polygon in self._select(page, *span).bounds()]
            if not polygons:
                continue
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for polygon in polygons:
                path.addPolygon(polygon)
                path.closeSubpath()
            self._shapes.setdefault(page, []).append((path.simplified(), mark.color))
            self._where.setdefault(
                mark.chunk_idx, (page, path.boundingRect().top()))
            return True
        return False

    def _text(self, page: int) -> PageText:
        if page not in self._texts:
            self._raw[page] = self.pdf.getAllText(page).text()
            self._texts[page] = letters_of(self._raw[page])
        return self._texts[page]

    def _select(self, page: int, start: int, length: int):
        """The selection for a span of the page text.

        QtPdf counts some characters differently from the text it returns
        (line ends, characters outside the basic plane), so further down a
        page a selection can begin a few characters early. The start is
        moved until the selected text begins where the span does.
        """
        raw = self._raw[page]
        want = raw[start:start + PROBE]
        at = start
        selection = self.pdf.getSelectionAtIndex(page, at, length)
        for _ in range(4):
            got = selection.text()
            if got[:PROBE] == want:
                break
            # Where does the selected text begin in the page text?
            begins = -1
            for skip in (0, 2, 4):
                found = raw.rfind(got[skip:skip + PROBE], max(start - 400, 0),
                                  start + 400)
                if len(got) >= skip + PROBE and found >= 0:
                    begins = found - skip
                    break
            if begins < 0 or begins == start:
                break
            at = max(at + start - begins, 0)
            selection = self.pdf.getSelectionAtIndex(page, at, length)
        return selection

    def scroll_to(self, chunk_idx: int, page: int) -> None:
        """Bring a passage into view: its marker, or else the top of its page
        (``page`` is 1-based)."""
        if not self.pages:
            return
        index, y = self._where.get(chunk_idx, (page - 1, 0.0))
        index = min(max(index, 0), len(self.pages) - 1)
        scale = (self.pages[index].width()
                 / max(self.pdf.pagePointSize(index).width(), 1.0))
        self._goto = max(int(self._tops[index] + y * scale) - 48, 0)
        # The scroll range follows the page sizes only after the pending
        # layout pass.
        QTimer.singleShot(0, self._apply_goto)

    def _apply_goto(self) -> None:
        if self._goto is not None:
            self.verticalScrollBar().setValue(self._goto)
        self._goto = None
        self._render_visible()

    # -- layout and rendering ------------------------------------------------ #
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self.pages and self._page_width() != self.pages[0].width():
            self._relayout.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._render_visible()

    def _page_width(self) -> int:
        return max(self.viewport().width() - 2 * MARGIN, MIN_WIDTH)

    def _layout_pages(self) -> None:
        """Fit every page to the width of the view."""
        if not self.pages:
            return
        bar = self.verticalScrollBar()
        position = bar.value() / bar.maximum() if bar.maximum() else 0.0
        width = self._page_width()
        tops: list[int] = []
        top = MARGIN
        for i, page in enumerate(self.pages):
            size = self.pdf.pagePointSize(i)
            height = round(width * size.height() / max(size.width(), 1.0))
            page.setFixedSize(width, height)
            page.clear()
            tops.append(top)
            top += height + GAP
        self._tops = tops
        self._rendered.clear()
        if self._goto is None:
            self._goto = int(position * max(top - self.viewport().height(), 0))
        QTimer.singleShot(0, self._apply_goto)

    def _render_visible(self) -> None:
        """Render the pages in view (and their neighbours); free the others."""
        if not self.pages or not self._tops or not self.isVisible():
            return
        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        wanted = {i for i, page in enumerate(self.pages)
                  if self._tops[i] + page.height() >= top - page.height()
                  and self._tops[i] <= bottom + page.height()}
        for i in self._rendered - wanted:
            self.pages[i].clear()
        for i in sorted(wanted - self._rendered):
            self._render(i)
        self._rendered = wanted

    def _render(self, index: int) -> None:
        page = self.pages[index]
        ratio = self.devicePixelRatioF()
        size = QSize(round(page.width() * ratio), round(page.height() * ratio))
        image = QImage(size, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.drawImage(0, 0, self.pdf.render(index, size))
        painter.save()
        scale = size.width() / max(self.pdf.pagePointSize(index).width(), 1.0)
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Multiply keeps the text under the marker black, like a real marker.
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Multiply)
        painter.setPen(Qt.PenStyle.NoPen)
        for path, color in self._shapes.get(index, []):
            painter.fillPath(path, QColor(color))
        painter.restore()
        painter.setPen(QColor(C.border))
        painter.drawRect(0, 0, size.width() - 1, size.height() - 1)
        painter.end()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        page.setPixmap(pixmap)
