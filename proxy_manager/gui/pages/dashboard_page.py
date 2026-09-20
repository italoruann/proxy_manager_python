"""Página inicial: status do motor, atalho para ligar/desligar, métricas rápidas e as
conexões mais recentes."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableView,
    QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..log_model import format_bytes
from ..widgets.cards import StatCard, StatusDot
from ..widgets.sparkline import Sparkline


class DashboardPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._last_total_bytes = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Visão geral do motor de proxy em tempo real.")
        subtitle.setObjectName("PageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self.status_dot = StatusDot("Motor parado", "text_faint")
        self.toggle_btn = QPushButton("Iniciar motor")
        self.toggle_btn.setObjectName("EngineToggleOff")
        self.toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        header.addWidget(self.status_dot)
        header.addWidget(self.toggle_btn)
        root.addLayout(header)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        self.card_status = StatCard("Status do motor", "Parado", "Local: 127.0.0.1")
        self.card_active = StatCard("Conexões ativas", "0")
        self.card_total = StatCard("Conexões (sessão)", "0")
        self.card_bytes = StatCard("Dados transferidos", "0 B", "via proxy: 0 B · direto: 0 B")
        for card in (self.card_status, self.card_active, self.card_total, self.card_bytes):
            cards_row.addWidget(card)
        root.addLayout(cards_row)

        chart_card = QFrame()
        chart_card.setObjectName("Card")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(18, 14, 18, 14)
        chart_title = QLabel("Taxa de transferência (bytes/s, últimos 60s)")
        chart_title.setObjectName("CardTitle")
        self.sparkline = Sparkline()
        chart_layout.addWidget(chart_title)
        chart_layout.addWidget(self.sparkline)
        root.addWidget(chart_card)

        recent_label = QLabel("Conexões recentes")
        recent_label.setObjectName("SectionTitle")
        root.addWidget(recent_label)

        self.recent_table = QTableView()
        self.recent_table.setModel(ctx.log_model)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recent_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.recent_table.setMaximumHeight(220)
        root.addWidget(self.recent_table, 1)

        ctx.status_changed.connect(self._on_status_changed)
        ctx.log_added.connect(lambda _entries: self._refresh_counters())
        ctx.log_updated.connect(lambda _entries: self._refresh_counters())

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        self._sync_initial_state()

    def _sync_initial_state(self) -> None:
        running = self.ctx.engine.is_running()
        self._on_status_changed(running, "Motor iniciado" if running else "Motor parado")

    def _on_toggle_clicked(self) -> None:
        if self.ctx.engine.is_running():
            self.ctx.engine.stop()
        else:
            self.ctx.engine.start()

    def _on_status_changed(self, running: bool, _message: str) -> None:
        if running:
            self.status_dot.set_state("Motor ativo", "success")
            self.toggle_btn.setText("Parar motor")
            self.toggle_btn.setObjectName("EngineToggleOn")
            self.card_status.set_value("Ativo")
            self.card_status.set_value_color("success")
        else:
            self.status_dot.set_state("Motor parado", "text_faint")
            self.toggle_btn.setText("Iniciar motor")
            self.toggle_btn.setObjectName("EngineToggleOff")
            self.card_status.set_value("Parado")
            self.card_status.set_value_color("text")
        # força o Qt a reaplicar o QSS após trocar o objectName
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)
        self._refresh_counters()

    def _refresh_counters(self) -> None:
        engine = self.ctx.engine
        self.card_active.set_value(str(engine.active_connections))
        self.card_total.set_value(str(self.ctx.log_model.rowCount()))

        total = engine.total_bytes_sent + engine.total_bytes_recv
        proxy_total = engine.proxy_bytes_sent + engine.proxy_bytes_recv
        direct_total = engine.direct_bytes_sent + engine.direct_bytes_recv
        self.card_bytes.set_value(format_bytes(total))
        # Números reais, medidos byte a byte no relay do motor — não é uma estimativa. Ver
        # ProxyEngine._pipe(): cada chunk que passa pelo túnel é contado na hora, por categoria.
        self.card_bytes.set_hint(f"via proxy: {format_bytes(proxy_total)} · direto: {format_bytes(direct_total)}")

        settings = self.ctx.config.settings
        self.card_status.set_hint(f"SOCKS5 {settings.socks_port} · HTTP {settings.http_port}")

    def _on_tick(self) -> None:
        engine = self.ctx.engine
        total = engine.total_bytes_sent + engine.total_bytes_recv
        delta = max(total - self._last_total_bytes, 0)
        self._last_total_bytes = total
        self.sparkline.push(float(delta))
        self._refresh_counters()
