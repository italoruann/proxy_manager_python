from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import PALETTE


class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—", hint: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        self._title = QLabel(title)
        self._title.setObjectName("CardTitle")
        self._value = QLabel(value)
        self._value.setObjectName("CardValue")
        self._hint = QLabel(hint)
        self._hint.setObjectName("CardHint")
        self._hint.setVisible(bool(hint))

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._hint)
        layout.addStretch(1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_hint(self, hint: str) -> None:
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))

    def set_value_color(self, color_key: str) -> None:
        color = PALETTE.get(color_key, PALETTE["text"])
        self._value.setStyleSheet(f"color: {color};")


class StatusDot(QWidget):
    """Um pequeno círculo colorido + texto, usado para indicar estado (ativo/parado)."""

    def __init__(self, text: str = "", color_key: str = "text_faint", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._label = QLabel(text)
        layout.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        self.set_state(text, color_key)

    def set_state(self, text: str, color_key: str) -> None:
        color = PALETTE.get(color_key, PALETTE["text_faint"])
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        self._label.setText(text)
        self._label.setStyleSheet(f"color: {color}; font-weight: 600;")
