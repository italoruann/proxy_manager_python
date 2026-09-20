"""Página de Configurações: portas locais, integração com o sistema, retenção de logs e
preferências gerais."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ...core import autostart, system_integration
from ...core.config import data_dir


def _card(title_text: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(10)
    title = QLabel(title_text)
    title.setObjectName("CardTitle")
    layout.addWidget(title)
    return frame, layout


class SettingsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("Configurações")
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        root.addWidget(self._build_ports_card())
        root.addWidget(self._build_integration_card())
        root.addWidget(self._build_rules_default_card())
        root.addWidget(self._build_logs_card())
        root.addWidget(self._build_general_card())
        root.addWidget(self._build_transparent_card())
        root.addStretch(1)

    # -- portas -----------------------------------------------------------------

    def _build_ports_card(self) -> QFrame:
        frame, layout = _card("Portas locais")
        form = QFormLayout()
        settings = self.ctx.config.settings

        self.socks_port_spin = QSpinBox()
        self.socks_port_spin.setRange(1024, 65535)
        self.socks_port_spin.setValue(settings.socks_port)
        self.http_port_spin = QSpinBox()
        self.http_port_spin.setRange(1024, 65535)
        self.http_port_spin.setValue(settings.http_port)
        self.pac_port_spin = QSpinBox()
        self.pac_port_spin.setRange(1024, 65535)
        self.pac_port_spin.setValue(settings.pac_port)

        form.addRow("Porta SOCKS5", self.socks_port_spin)
        form.addRow("Porta HTTP/HTTPS", self.http_port_spin)
        form.addRow("Porta do arquivo PAC", self.pac_port_spin)
        layout.addLayout(form)

        hint = QLabel("Sempre em 127.0.0.1 (apenas local). Se o motor estiver ativo, "
                       "ele será reiniciado automaticamente ao salvar.")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        save_btn = QPushButton("Salvar portas")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._on_save_ports)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save_btn)
        layout.addLayout(row)
        return frame

    def _on_save_ports(self) -> None:
        settings = self.ctx.config.settings
        settings.socks_port = self.socks_port_spin.value()
        settings.http_port = self.http_port_spin.value()
        settings.pac_port = self.pac_port_spin.value()
        was_running = self.ctx.engine.is_running()
        if was_running:
            self.ctx.engine.stop()
        self.ctx.apply_config_changes()
        if was_running:
            self.ctx.engine.start()
        QMessageBox.information(self, "Portas", "Portas atualizadas.")

    # -- integração com o sistema -----------------------------------------------

    def _build_integration_card(self) -> QFrame:
        frame, layout = _card("Integração com o sistema")
        settings = self.ctx.config.settings

        self.integration_check = QCheckBox("Configurar automaticamente o proxy do sistema (via PAC)")
        self.integration_check.setChecked(settings.system_integration_enabled)
        layout.addWidget(self.integration_check)

        pac_row = QHBoxLayout()
        self.pac_url_edit = QLineEdit(system_integration.pac_url(settings.pac_port))
        self.pac_url_edit.setReadOnly(True)
        pac_row.addWidget(QLabel("URL do PAC:"))
        pac_row.addWidget(self.pac_url_edit, 1)
        layout.addLayout(pac_row)

        hint = QLabel(
            "Aplica um script PAC que direciona todo o tráfego para o Proxy Manager, que então "
            "decide o roteamento pelas suas regras. Essa configuração liga e desliga sozinha "
            "junto com o motor (Dashboard) — assim sua internet nunca fica presa apontando para "
            "um proxy que não está rodando. Os botões abaixo são só para forçar manualmente. "
            "No Firefox, pode ser necessário colar essa URL em Configurações → Rede → "
            "Configuração automática de proxy."
        )
        hint.setWordWrap(True)
        hint.setObjectName("CardHint")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        apply_btn = QPushButton("Aplicar agora")
        apply_btn.setObjectName("PrimaryButton")
        apply_btn.clicked.connect(self._on_apply_integration)
        remove_btn = QPushButton("Remover")
        remove_btn.clicked.connect(self._on_remove_integration)
        buttons.addWidget(apply_btn)
        buttons.addWidget(remove_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.integration_result_label = QLabel("")
        self.integration_result_label.setWordWrap(True)
        layout.addWidget(self.integration_result_label)
        return frame

    def _on_apply_integration(self) -> None:
        settings = self.ctx.config.settings
        settings.system_integration_enabled = True
        self.integration_check.setChecked(True)
        self.ctx.apply_config_changes()
        if self.ctx.engine.is_running():
            ok, message = system_integration.apply_system_proxy(
                system_integration.pac_url(settings.pac_port), settings.http_port)
            self.integration_result_label.setText(("✔ " if ok else "✘ ") + message)
        else:
            # Aplicar agora com o motor parado deixaria o SO apontando para um PAC morto (o
            # exato problema que causa lentidão de internet) — só salvamos a preferência; ela é
            # aplicada sozinha assim que o motor iniciar.
            self.integration_result_label.setText(
                "Preferência salva. Será aplicada automaticamente assim que você iniciar o "
                "motor no Dashboard, e removida sozinha quando ele parar.")

    def _on_remove_integration(self) -> None:
        settings = self.ctx.config.settings
        settings.system_integration_enabled = False
        self.integration_check.setChecked(False)
        self.ctx.apply_config_changes()
        ok, message = system_integration.remove_system_proxy()
        self.integration_result_label.setText(("✔ " if ok else "✘ ") + message)

    # -- ação padrão --------------------------------------------------------------

    def _build_rules_default_card(self) -> QFrame:
        frame, layout = _card("Comportamento padrão")
        form = QFormLayout()
        self.default_action_combo = QComboBox()
        self.default_action_combo.addItem("Ir direto (sem proxy)", "direct")
        self.default_action_combo.addItem("Bloquear", "block")
        index = self.default_action_combo.findData(self.ctx.config.settings.default_action)
        self.default_action_combo.setCurrentIndex(max(index, 0))
        self.default_action_combo.currentIndexChanged.connect(self._on_default_action_changed)
        form.addRow("Quando nenhuma regra casar", self.default_action_combo)
        layout.addLayout(form)
        return frame

    def _on_default_action_changed(self, _index: int) -> None:
        self.ctx.config.settings.default_action = self.default_action_combo.currentData()
        self.ctx.apply_config_changes()

    # -- logs -----------------------------------------------------------------------

    def _build_logs_card(self) -> QFrame:
        frame, layout = _card("Logs")
        form = QFormLayout()
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 365)
        self.retention_spin.setSuffix(" dias")
        self.retention_spin.setValue(self.ctx.config.settings.log_retention_days)
        self.retention_spin.valueChanged.connect(self._on_retention_changed)
        form.addRow("Manter histórico salvo por", self.retention_spin)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        open_folder_btn = QPushButton("Abrir pasta de dados")
        open_folder_btn.clicked.connect(self._on_open_data_folder)
        clear_btn = QPushButton("Limpar histórico salvo")
        clear_btn.setObjectName("DangerButton")
        clear_btn.clicked.connect(self._on_clear_history)
        buttons.addWidget(open_folder_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return frame

    def _on_retention_changed(self, value: int) -> None:
        self.ctx.config.settings.log_retention_days = value
        self.ctx.apply_config_changes()

    def _on_open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    def _on_clear_history(self) -> None:
        confirm = QMessageBox.question(self, "Limpar histórico",
                                        "Apagar todo o histórico de conexões salvo em disco? "
                                        "Isso não pode ser desfeito.")
        if confirm == QMessageBox.StandardButton.Yes:
            self.ctx.log_store.clear_persisted()
            QMessageBox.information(self, "Histórico", "Histórico salvo apagado.")

    # -- geral -----------------------------------------------------------------------

    def _build_general_card(self) -> QFrame:
        frame, layout = _card("Geral")
        self.start_minimized_check = QCheckBox("Iniciar minimizado na bandeja do sistema")
        self.start_minimized_check.setChecked(self.ctx.config.settings.start_minimized)
        self.start_minimized_check.toggled.connect(self._on_start_minimized_toggled)
        layout.addWidget(self.start_minimized_check)

        self.autostart_check = QCheckBox("Iniciar automaticamente com o sistema")
        self.autostart_check.setChecked(autostart.is_enabled())
        self.autostart_check.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self.autostart_check)
        return frame

    def _on_start_minimized_toggled(self, checked: bool) -> None:
        self.ctx.config.settings.start_minimized = checked
        self.ctx.apply_config_changes()

    def _on_autostart_toggled(self, checked: bool) -> None:
        ok, message = autostart.set_enabled(checked)
        if not ok:
            QMessageBox.warning(self, "Início automático", message)
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not checked)
            self.autostart_check.blockSignals(False)

    # -- modo transparente (futuro) -----------------------------------------------

    def _build_transparent_card(self) -> QFrame:
        frame, layout = _card("Modo transparente (em breve)")
        check = QCheckBox("Capturar qualquer aplicativo sem configuração (iptables/WinDivert)")
        check.setEnabled(False)
        layout.addWidget(check)
        hint = QLabel(
            "Fase 2 do projeto: interceptação em nível de sistema, sem precisar configurar cada "
            "app. Vai exigir privilégios de administrador/root. O modo explícito acima já garante "
            "que qualquer app que respeite as configurações de proxy do sistema seja capturado."
        )
        hint.setWordWrap(True)
        hint.setObjectName("CardHint")
        layout.addWidget(hint)
        return frame
