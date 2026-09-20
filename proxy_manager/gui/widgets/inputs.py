from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class PasswordEdit(QWidget):
    """QLineEdit em modo senha com um botão para mostrar/ocultar o texto."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)

        self._toggle = QPushButton("Mostrar")
        self._toggle.setCheckable(True)
        self._toggle.setFixedWidth(76)
        self._toggle.toggled.connect(self._on_toggled)

        layout.addWidget(self.edit, 1)
        layout.addWidget(self._toggle)

    def _on_toggled(self, checked: bool) -> None:
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
        self._toggle.setText("Ocultar" if checked else "Mostrar")

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:
        self.edit.setText(value)
