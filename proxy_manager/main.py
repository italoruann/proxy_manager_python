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

    _quit_on_termination_signals(app, window._quit_app)
    sys.exit(app.exec())


def _quit_on_termination_signals(app, quit_app) -> None:
    """SIGTERM (pkill, logout, scripts de build reinstalando) e Ctrl+C no terminal passam a sair
    pelo mesmo caminho do "Sair": o motor para e desfaz o proxy dos navegadores/sistema. Sem isso
    o processo morria na hora e deixava tudo apontando para um PAC morto."""
    import signal

    from PySide6.QtCore import QTimer

    def handler(_signum, _frame) -> None:
        quit_app()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass
    # O Python só roda handlers de sinal quando ganha o controle; parado dentro do loop do Qt, isso
    # nunca acontece. Um timer vazio devolve o controle a ele periodicamente.
    timer = QTimer(app)
    timer.timeout.connect(lambda: None)
    timer.start(300)


if __name__ == "__main__":
    main()
