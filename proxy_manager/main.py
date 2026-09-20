"""Ponto de entrada: `python -m proxy_manager`."""
from __future__ import annotations

import sys


def main() -> None:
    from PySide6.QtWidgets import QApplication

    from .gui.app_context import AppContext
    from .gui.icon import render_icon
    from .gui.main_window import MainWindow
    from .gui.theme import build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName("Proxy Manager")
    app.setQuitOnLastWindowClosed(False)  # a janela é escondida (bandeja), não fechada de fato
    app.setStyleSheet(build_stylesheet())
    app.setWindowIcon(render_icon(False))

    ctx = AppContext()
    window = MainWindow(ctx)

    start_minimized = "--start-minimized" in sys.argv or ctx.config.settings.start_minimized
    if not start_minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
