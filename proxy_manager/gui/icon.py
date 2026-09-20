"""Ícone da aplicação gerado em código (sem depender de arquivos de imagem externos)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap

from .theme import PALETTE


def render_icon(active: bool = False, size: int = 256) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    rect = QRectF(size * 0.06, size * 0.06, size * 0.88, size * 0.88)
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.22, size * 0.22)

    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(PALETTE["accent_hover"]))
    gradient.setColorAt(1, QColor(PALETTE["accent_pressed"]))
    painter.fillPath(path, gradient)

    font = QFont("Segoe UI", int(size * 0.42))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#0b1020"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "P")

    if active:
        dot_d = size * 0.22
        dot_rect = QRectF(size - dot_d - size * 0.02, size - dot_d - size * 0.02, dot_d, dot_d)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#12141c"))
        painter.drawEllipse(dot_rect.adjusted(-3, -3, 3, 3))
        painter.setBrush(QColor(PALETTE["success"]))
        painter.drawEllipse(dot_rect)

    painter.end()
    return QIcon(pixmap)
