"""Ponto de entrada: `python -m proxy_manager`."""
from __future__ import annotations

import sys


def main() -> None:
    from .linux_qt_deps import ensure_qt_system_libs

    ensure_qt_system_libs()  # tem que rodar antes do QApplication carregar o plugin de plataforma

    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

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

    settings = ctx.config.settings
    start_minimized = "--start-minimized" in sys.argv or settings.start_minimized
    # Iniciar minimizado só faz sentido com a opção de manter na bandeja ligada. Sem bandeja do
    # sistema (comum no GNOME sem extensão), deixaria o processo rodando sem janela e sem ícone
    # algum para reabri-lo.
    if not (start_minimized and settings.minimize_to_tray and QSystemTrayIcon.isSystemTrayAvailable()):
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
