"""Janela principal: sidebar de navegação + páginas + ícone na bandeja do sistema."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QPushButton,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from .app_context import AppContext
from .icon import render_icon
from .pages.dashboard_page import DashboardPage
from .pages.logs_page import LogsPage
from .pages.proxies_page import ProxiesPage
from .pages.rules_page import RulesPage
from .pages.settings_page import SettingsPage

NAV_ITEMS = ["Dashboard", "Proxies", "Regras", "Logs", "Configurações"]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Proxy Manager")
        self.resize(1200, 780)
        self.setMinimumSize(1000, 640)
        self.setWindowIcon(render_icon(False))

        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage(ctx)
        self.proxies_page = ProxiesPage(ctx)
        self.rules_page = RulesPage(ctx)
        self.logs_page = LogsPage(ctx)
        self.settings_page = SettingsPage(ctx)
        for page in (self.dashboard_page, self.proxies_page, self.rules_page,
                     self.logs_page, self.settings_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.nav_buttons[0].setChecked(True)

        self._build_tray_icon()
        ctx.status_changed.connect(self._on_status_changed_tray)

    def _build_sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(228)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 22, 16, 16)
        layout.setSpacing(4)

        brand = QLabel("Proxy Manager")
        brand.setObjectName("BrandTitle")
        subtitle = QLabel("roteamento avançado de proxy")
        subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(brand)
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        self.nav_buttons: list[QPushButton] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for index, label in enumerate(NAV_ITEMS):
            btn = QPushButton(label)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, i=index: self.stack.setCurrentIndex(i))
            self._nav_group.addButton(btn)
            layout.addWidget(btn)
            self.nav_buttons.append(btn)

        layout.addStretch(1)
        version_label = QLabel("v0.1.0 · modo explícito")
        version_label.setObjectName("BrandSubtitle")
        layout.addWidget(version_label)
        return frame

    # -- bandeja do sistema -------------------------------------------------

    def _build_tray_icon(self) -> None:
        self.tray: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            # Sem bandeja (comum no GNOME sem a extensão AppIndicator, por exemplo): não dá pra
            # contar com ela para reabrir a janela depois. self.tray fica None e closeEvent()
            # trata isso fechando o app de verdade, em vez de só esconder a janela.
            return

        self.tray = QSystemTrayIcon(render_icon(False), self)
        self.tray.setToolTip("Proxy Manager — parado")

        menu = QMenu()
        self.tray_toggle_action = menu.addAction("Iniciar motor")
        self.tray_toggle_action.triggered.connect(self._toggle_engine_from_tray)
        menu.addAction("Abrir janela", self._show_and_raise)
        menu.addSeparator()
        menu.addAction("Sair", self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_status_changed_tray(self, running: bool, _message: str) -> None:
        if self.tray is None:
            return
        self.tray.setIcon(render_icon(running))
        self.tray_toggle_action.setText("Parar motor" if running else "Iniciar motor")
        self.tray.setToolTip(f"Proxy Manager — {'ativo' if running else 'parado'}")

    def _toggle_engine_from_tray(self) -> None:
        if self.ctx.engine.is_running():
            self.ctx.engine.stop()
        else:
            self.ctx.engine.start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_and_raise()

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        self.ctx.engine.stop()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self.tray is None:
            # Sem bandeja não há como reabrir a janela depois — esconder aqui deixaria o
            # processo rodando invisível, sem nenhum jeito de voltar a ele além de matá-lo pelo
            # terminal. Fecha de verdade, como qualquer outro programa.
            self.ctx.engine.stop()
            event.accept()
            QApplication.instance().quit()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage("Proxy Manager", "Continua rodando na bandeja do sistema.",
                               QSystemTrayIcon.MessageIcon.Information, 3000)
