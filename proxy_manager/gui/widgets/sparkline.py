"""Mini gráfico de linha (sparkline) desenhado à mão com QPainter — evita depender de uma
biblioteca de gráficos só para mostrar a taxa de transferência recente."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..theme import PALETTE


class Sparkline(QWidget):
    def __init__(self, max_points: int = 60, parent: QWidget | None = None):
        super().__init__(parent)
        self._values: deque[float] = deque([0.0] * max_points, maxlen=max_points)
        self.setMinimumHeight(64)

    def push(self, value: float) -> None:
        self._values.append(value)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        values = list(self._values)
        max_val = max(values) if any(values) else 1.0
        max_val = max(max_val, 1.0)

        w, h = rect.width(), rect.height()
        pad = 4
        step = (w - 2 * pad) / max(len(values) - 1, 1)

        points = []
        for i, v in enumerate(values):
            x = pad + i * step
            y = h - pad - (v / max_val) * (h - 2 * pad)
            points.append(QPointF(x, y))

        if len(points) >= 2:
            fill_path = QPainterPath(points[0])
            for pt in points[1:]:
                fill_path.lineTo(pt)
            fill_path.lineTo(points[-1].x(), h)
            fill_path.lineTo(points[0].x(), h)
            fill_path.closeSubpath()

            gradient = QLinearGradient(0, 0, 0, h)
            accent = QColor(PALETTE["accent"])
            top = QColor(accent)
            top.setAlpha(90)
            bottom = QColor(accent)
            bottom.setAlpha(0)
            gradient.setColorAt(0, top)
            gradient.setColorAt(1, bottom)
            painter.fillPath(fill_path, gradient)

            line_path = QPainterPath(points[0])
            for pt in points[1:]:
                line_path.lineTo(pt)
            pen = QPen(accent, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(line_path)
        painter.end()
