"""Small reusable widgets shared by all pages."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..services import Doc
from .theme import C, VERDICTS, badge_style


def label(text: str = "", kind: str = "", wrap: bool = True,
          selectable: bool = False) -> QLabel:
    """A QLabel with one of the theme's styles (h1, h2, title, muted, …)."""
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    lbl.setWordWrap(wrap)
    if kind:
        lbl.setObjectName(kind)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def button(text: str, kind: str = "", on_click=None) -> QPushButton:
    btn = QPushButton(text)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        btn.setObjectName(kind)
    if on_click:
        btn.clicked.connect(lambda _checked=False: on_click())
    return btn


def badge(text: str, color: str = C.primary) -> QLabel:
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    lbl.setStyleSheet(badge_style(color))
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
    return lbl


def verdict_badge(verdict: str) -> QLabel:
    text, color = VERDICTS.get(verdict, (verdict, C.muted_fg))
    return badge(text, color)


class LinkLabel(QLabel):
    """Clickable text that wraps (a QPushButton would force its full width)."""
    clicked = pyqtSignal()

    def __init__(self, text: str, on_click=None):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setObjectName("linkLabel")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if on_click:
            self.clicked.connect(on_click)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton \
                and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)   # disappear now, not on the next loop
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


class Card(QFrame):
    """White rounded panel; emits ``clicked`` when ``clickable``."""
    clicked = pyqtSignal()

    def __init__(self, clickable: bool = False, margins: int = 14):
        super().__init__()
        self.setObjectName("card")
        self._clickable = clickable
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(margins, margins, margins, margins)
        self.box.setSpacing(6)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._clickable and event.button() == Qt.MouseButton.LeftButton \
                and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _set_hover(self, on: bool) -> None:
        if self._clickable:
            self.setProperty("hover", on)
            self.style().unpolish(self)
            self.style().polish(self)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hover(False)
        super().leaveEvent(event)


class PageHeader(QWidget):
    """Page title + description, with room for action buttons on the right."""

    def __init__(self, title: str, desc: str = ""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 8)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = label(title, "h1")
        self.desc = label(desc, "muted")
        text.addWidget(self.title)
        text.addWidget(self.desc)
        row.addLayout(text, 1)
        self.actions = QHBoxLayout()
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget, 0, Qt.AlignmentFlag.AlignBottom)


class FlowLayout(QLayout):
    """Lays children out left-to-right and wraps them (for tags / chips)."""

    def __init__(self, spacing: int = 6):
        super().__init__()
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and row_height:
                x, y, row_height = rect.x(), y + row_height + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y()


def tag_row(tags: list[str], limit: int = 5) -> QWidget:
    """A wrapping row of tag badges."""
    holder = QWidget()
    flow = FlowLayout()
    holder.setLayout(flow)
    for t in tags[:limit]:
        flow.addWidget(badge(t, C.primary))
    if len(tags) > limit:
        flow.addWidget(badge(f"+{len(tags) - limit}", C.muted_fg))
    return holder


class DocCard(Card):
    """Library entry: title, authors · venue, tags. Click opens the paper."""

    def __init__(self, doc: Doc):
        super().__init__(clickable=True)
        self.doc = doc
        top = QHBoxLayout()
        title = label(doc.title, "title")
        top.addWidget(title, 1)
        if doc.starred:
            star = QLabel("★")
            star.setStyleSheet(f"color: {C.partial}; font-size: 15px;")
            top.addWidget(star, 0, Qt.AlignmentFlag.AlignTop)
        self.box.addLayout(top)
        meta = doc.author_line + (f" · {doc.venue}" if doc.venue else "")
        self.box.addWidget(label(meta, "muted"))
        tags = list(doc.tags)
        if doc.is_local:
            tags = ["PDF 追加"] + tags
        if tags:
            self.box.addWidget(tag_row(tags, limit=4))
        self.box.addStretch(1)
