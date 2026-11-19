"""Relation graph: citation links (solid arrows) and content similarity
(dashed lines) between the papers of the library."""
from __future__ import annotations

import math
from collections import Counter

from PyQt6.QtCore import QLineF, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QCheckBox, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QVBoxLayout, QWidget,
)

from ..graph import Graph, layout
from .theme import C, NO_TAG_COLOR, PALETTE
from .widgets import (Card, LinkLabel, PageHeader, button, clear_layout, label,
                      scrollable, tag_row)
from .workers import run_task

BASE_W, BASE_H = 800.0, 560.0
EDGE_COLOR = "#64748b"
KIND_LABEL = {"cites": "引用関係", "similar": "内容の類似"}


class NodeItem(QGraphicsEllipseItem):
    def __init__(self, key: str, radius: float):
        super().__init__(-radius, -radius, 2 * radius, 2 * radius)
        self.key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class GraphView(QGraphicsView):
    """Zoom with the wheel, pan by dragging, click a node to select it."""
    node_clicked = pyqtSignal(str)
    background_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._press = None

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._press = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._press is None:
            return
        moved = (event.position() - self._press).manhattanLength()
        self._press = None
        if moved > 4:
            return   # it was a pan, not a click
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        if item is not None:
            self.node_clicked.emit(item.key)
        else:
            self.background_clicked.emit()


class GraphPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.graph: Graph | None = None
        self.pos: dict[str, tuple[float, float]] = {}
        self.docs: dict = {}
        self.colors: dict[str, str] = {}
        self.sel: str | None = None
        self._stamp = None       # library state the cached graph was built for
        self._fit_pending = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(PageHeader(
            "関連グラフ",
            "引用関係（実線の矢印）と内容の近さ（点線）から文献同士のつながりを"
            "可視化します。ノードを選ぶと関連文献が強調されます。"))
        columns = QHBoxLayout()
        columns.setSpacing(14)
        outer.addLayout(columns, 1)

        canvas = Card(margins=0)
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 4)
        self.toggles: dict[str, QCheckBox] = {}
        for kind, text in KIND_LABEL.items():
            box = QCheckBox(text)
            box.setChecked(True)
            box.toggled.connect(lambda _on: self._draw())
            self.toggles[kind] = box
            bar.addWidget(box)
        bar.addWidget(button("全体を表示", "chip", self._fit))
        bar.addStretch(1)
        self.legend = QHBoxLayout()
        bar.addLayout(self.legend)
        canvas.box.addLayout(bar)
        self.scene = QGraphicsScene(self)
        self.view = GraphView()
        self.view.setScene(self.scene)
        self.view.node_clicked.connect(self._select)
        self.view.background_clicked.connect(lambda: self._select(None))
        canvas.box.addWidget(self.view, 1)
        self.info = label("", "muted")
        self.info.setContentsMargins(12, 0, 12, 8)
        canvas.box.addWidget(self.info)
        columns.addWidget(canvas, 1)

        detail = Card()
        self.detail = QVBoxLayout()
        detail.box.addLayout(self.detail)
        detail.box.addStretch(1)
        area = scrollable(detail)
        area.setFixedWidth(310)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        columns.addWidget(area)

    # -- data --------------------------------------------------------------- #
    def set_focus(self, key: str | None) -> None:
        self.sel = key

    def refresh(self) -> None:
        s = self.app.services
        stamp = (s.store.n_papers, s.store.n_vectors, s.config.graph_neighbors)
        if self.graph is not None and stamp == self._stamp:
            self._draw()
            self._show_detail()
            return
        self.info.setText("グラフを計算中…")

        def work():
            graph = s.graph()
            scale = max(1.0, math.sqrt(len(graph.nodes) / 10))
            pos = layout(graph.nodes, graph.edges, BASE_W * scale, BASE_H * scale)
            return stamp, graph, pos, {d.key: d for d in s.documents()}

        run_task(self, work, self._on_graph,
                 lambda err: self.info.setText(f"グラフの計算に失敗: {err}"))

    def _on_graph(self, result) -> None:
        self._stamp, self.graph, self.pos, self.docs = result
        if self.sel not in self.docs:
            self.sel = None
        first_tags = Counter(d.tags[0] for d in self.docs.values() if d.tags)
        ranked = [t for t, _ in first_tags.most_common()]
        self.colors = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(ranked)}
        clear_layout(self.legend)
        for tag in ranked[:3] + ["タグなし"]:
            dot = label("●", wrap=False)
            dot.setStyleSheet(f"color: {self.colors.get(tag, NO_TAG_COLOR)};")
            self.legend.addWidget(dot)
            # Long tag names must not widen the window: shorten + tooltip.
            short = tag if len(tag) <= 18 else "…" + tag[-17:]
            name = label(short, "muted", wrap=False)
            name.setToolTip(tag)
            self.legend.addWidget(name)
        self._fit_pending = True
        self._draw()
        self._show_detail()

    def _color(self, key: str) -> str:
        doc = self.docs.get(key)
        tag = doc.tags[0] if doc and doc.tags else None
        return self.colors.get(tag, NO_TAG_COLOR)

    def _edges(self):
        return [e for e in self.graph.edges if self.toggles[e.kind].isChecked()]

    # -- drawing ------------------------------------------------------------ #
    def _draw(self) -> None:
        if self.graph is None:
            return
        self.scene.clear()
        edges = self._edges()
        degree = Counter()
        for e in self.graph.edges:
            degree[e.source] += 1
            degree[e.target] += 1
        radius = {k: 9 + 2.5 * min(degree[k], 8) for k in self.graph.nodes}
        near = {self.sel}
        for e in edges:
            if e.source == self.sel:
                near.add(e.target)
            elif e.target == self.sel:
                near.add(e.source)

        for e in edges:
            a, b = QPointF(*self.pos[e.source]), QPointF(*self.pos[e.target])
            active = self.sel is None or self.sel in (e.source, e.target)
            color = QColor(EDGE_COLOR)
            color.setAlphaF(0.7 if active else 0.08)
            pen = QPen(color, 1.6 if e.kind == "cites" else 1.2)
            if e.kind == "similar":
                pen.setStyle(Qt.PenStyle.DashLine)
            line = QLineF(a, b)
            self.scene.addLine(line, pen).setZValue(0)
            if e.kind == "cites" and line.length() > 1:
                self._arrow(line, radius[e.target], color)

        for key in self.graph.nodes:
            doc = self.docs.get(key)
            if doc is None:
                continue
            node = NodeItem(key, radius[key])
            node.setPos(*self.pos[key])
            node.setBrush(QBrush(QColor(self._color(key))))
            selected = key == self.sel
            node.setPen(QPen(QColor("#facc15" if selected else "#ffffff"),
                             4 if selected else 2))
            node.setOpacity(1.0 if self.sel is None or key in near else 0.2)
            node.setToolTip(f"{doc.title}\n{doc.author_line}")
            node.setZValue(2)
            self.scene.addItem(node)
            text = self.scene.addSimpleText(doc.short_label)
            text.setBrush(QBrush(QColor(C.fg)))
            text.setParentItem(node)
            text.setPos(-text.boundingRect().width() / 2, radius[key] + 2)

        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(
            -30, -30, 30, 30))
        cites = sum(1 for e in self.graph.edges if e.kind == "cites")
        self.info.setText(
            f"文献 {len(self.graph.nodes)} 件 · 引用関係 {cites} 件 · "
            f"内容の類似 {len(self.graph.edges) - cites} 件 "
            "（ホイールで拡大縮小、ドラッグで移動）")
        if self._fit_pending and self.isVisible():
            self._fit_pending = False
            self._fit()

    def _arrow(self, line: QLineF, target_radius: float, color: QColor) -> None:
        """Arrow head on the rim of the cited (target) node."""
        unit = QPointF(line.dx() / line.length(), line.dy() / line.length())
        tip = line.p2() - unit * (target_radius + 2)
        normal = QPointF(-unit.y(), unit.x())
        base = tip - unit * 9
        head = QPolygonF([tip, base + normal * 4.5, base - normal * 4.5])
        self.scene.addPolygon(head, QPen(Qt.PenStyle.NoPen),
                              QBrush(color)).setZValue(1)

    def _fit(self) -> None:
        self.view.fitInView(self.scene.sceneRect(),
                            Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.graph is not None and self._fit_pending:
            self._fit_pending = False
            self._fit()

    # -- selection ---------------------------------------------------------- #
    def _select(self, key: str | None) -> None:
        self.sel = key
        self._draw()
        self._show_detail()

    def _show_detail(self) -> None:
        clear_layout(self.detail)
        doc = self.docs.get(self.sel) if self.sel else None
        if doc is None or self.graph is None:
            self.detail.addWidget(label(
                "ノードを選択すると\n文献の詳細と関連が表示されます", "muted"))
            return
        if doc.tags:
            self.detail.addWidget(tag_row(doc.tags, limit=6))
        self.detail.addWidget(label(doc.title, "h2"))
        meta = doc.author_line + (f" · {doc.venue}" if doc.venue else "")
        self.detail.addWidget(label(meta, "muted"))
        if doc.abstract:
            text = doc.abstract[:400] + ("…" if len(doc.abstract) > 400 else "")
            self.detail.addWidget(label(text))
        kinds = tuple(k for k, box in self.toggles.items() if box.isChecked())
        neighbours = self.graph.neighbours(doc.key, kinds)
        self.detail.addWidget(label(f"つながっている文献（{len(neighbours)}）", "muted"))
        for other, edge in neighbours:
            target = self.docs.get(other)
            if target is None:
                continue
            if edge.kind == "similar":
                relation = "≈ 内容が近い"
            elif edge.source == doc.key:
                relation = "→ 引用している"
            else:
                relation = "← 引用されている"
            self.detail.addWidget(LinkLabel(
                target.title, lambda k=other: self._select(k)))
            self.detail.addWidget(label(relation, "muted"))
        self.detail.addWidget(button(
            "文献を開く →", on_click=lambda: self.app.open_document(doc.key)))
