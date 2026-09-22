"""Atalho fixo perto do botão de ligar/desligar o motor: troca qual perfil de proxy está
ativo (padrão) e permite editar suas credenciais sem sair do Dashboard nem navegar até a
página de Proxies."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ...core.config import ProxyProfile
from .inputs import PasswordEdit


class ProxyCredentialsDialog(QDialog):
    """Formulário compacto para criar ou editar host/porta/credenciais de um perfil de proxy."""

    def __init__(self, ctx: AppContext, profile: ProxyProfile | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._profile = profile
        self._test_worker = None

        self.setWindowTitle("Novo perfil de proxy" if profile is None else f"Editar proxy — {profile.name}")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit(profile.name if profile else f"Novo proxy {len(ctx.config.proxies) + 1}")
        self.type_combo = QComboBox()
        self.type_combo.addItem("SOCKS5", "socks5")
        self.type_combo.addItem("HTTP / HTTPS (CONNECT)", "http")
        if profile is not None:
            self.type_combo.setCurrentIndex(max(self.type_combo.findData(profile.type), 0))
        self.host_edit = QLineEdit(profile.host if profile else "")
        self.host_edit.setPlaceholderText("ex.: proxy.minhaempresa.com")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(profile.port if profile else 1080)
        self.user_edit = QLineEdit(profile.username if profile else "")
        self.user_edit.setPlaceholderText("(opcional)")
        self.password_edit = PasswordEdit()
        self.password_edit.setText(profile.password if profile else "")
        self.default_check = QCheckBox("Usar como proxy padrão")
        self.default_check.setChecked(profile.is_default if profile else not ctx.config.proxies)

        form.addRow("Nome", self.name_edit)
        form.addRow("Tipo", self.type_combo)
        form.addRow("Host", self.host_edit)
        form.addRow("Porta", self.port_spin)
        form.addRow("Usuário", self.user_edit)
        form.addRow("Senha", self.password_edit)
        form.addRow("", self.default_check)
        layout.addLayout(form)

        self.result_label = QLabel("")
        self.result_label.setObjectName("CardHint")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        test_row = QHBoxLayout()
        test_btn = QPushButton("Testar conexão")
        test_btn.clicked.connect(self._on_test)
        test_row.addWidget(test_btn)
        test_row.addStretch(1)
        layout.addLayout(test_row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_btn = box.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("Salvar")
        save_btn.setObjectName("PrimaryButton")
        box.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        box.accepted.connect(self._on_save)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_test(self) -> None:
        from ..workers import ProxyTestWorker  # import tardio: evita ciclo de import no módulo
        candidate = ProxyProfile(
            name=self.name_edit.text(), type=self.type_combo.currentData(),
            host=self.host_edit.text().strip(), port=self.port_spin.value(),
            username=self.user_edit.text(), password=self.password_edit.text(),
        )
        self.result_label.setText("Testando conexão…")
        self._test_worker = ProxyTestWorker(candidate)
        self._test_worker.finished_test.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        self.result_label.setText(("✔ " if ok else "✘ ") + message)

    def _on_save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Perfil de proxy", "Informe um nome para o perfil.")
            return
        host = self.host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Perfil de proxy", "Informe o host do proxy.")
            return

        profile = self._profile
        if profile is None:
            profile = ProxyProfile()
            self.ctx.config.proxies.append(profile)
            self._profile = profile

        profile.name = name
        profile.type = self.type_combo.currentData()
        profile.host = host
        profile.port = self.port_spin.value()
        profile.username = self.user_edit.text()
        profile.password = self.password_edit.text()
        profile.enabled = True
        profile.is_default = self.default_check.isChecked()

        if profile.is_default:
            for other in self.ctx.config.proxies:
                if other.id != profile.id:
                    other.is_default = False
        self.ctx.config.ensure_single_default()

        self.ctx.apply_config_changes()
        self.accept()


class QuickProxyBar(QFrame):
    """Rótulo + seletor de proxy padrão + menu de ações rápidas (editar/criar/gerenciar),
    pensado para ficar colado no botão de ligar/desligar o motor no Dashboard."""

    manage_requested = Signal()

    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("QuickProxyBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        layout.setSpacing(8)

        label_box = QVBoxLayout()
        label_box.setSpacing(2)
        caption = QLabel("PROXY ATIVO")
        caption.setObjectName("QuickProxyLabel")
        label_box.addWidget(caption)
        self.combo = QComboBox()
        self.combo.setObjectName("QuickProxyCombo")
        self.combo.setToolTip(
            "Perfil de proxy usado como padrão pelas regras que não especificam um proxy.")
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        label_box.addWidget(self.combo)
        layout.addLayout(label_box)

        self.actions_btn = QPushButton("⚙")
        self.actions_btn.setObjectName("IconButton")
        self.actions_btn.setFixedWidth(36)
        self.actions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.actions_btn.setToolTip("Editar credenciais, criar ou gerenciar perfis de proxy")

        menu = QMenu(self.actions_btn)
        self.edit_action = menu.addAction("✎  Editar credenciais…")
        self.edit_action.triggered.connect(self._on_edit)
        new_action = menu.addAction("+  Novo perfil…")
        new_action.triggered.connect(self._on_new)
        menu.addSeparator()
        manage_action = menu.addAction("Gerenciar todos os perfis")
        manage_action.triggered.connect(self.manage_requested.emit)
        self.actions_btn.setMenu(menu)
        layout.addWidget(self.actions_btn)

        ctx.config_changed.connect(self._reload)
        self._reload()

    def _reload(self) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for profile in self.ctx.config.proxies:
            text = profile.name if profile.enabled else f"{profile.name}  (desabilitado)"
            self.combo.addItem(text, profile.id)

        if self.combo.count() == 0:
            self.combo.addItem("Nenhum perfil cadastrado", None)
            self.edit_action.setEnabled(False)
        else:
            self.edit_action.setEnabled(True)
            default = self.ctx.config.default_proxy()
            target_id = default.id if default else self.ctx.config.proxies[0].id
            self.combo.setCurrentIndex(max(self.combo.findData(target_id), 0))
        self.combo.blockSignals(False)

    def _current_profile(self) -> ProxyProfile | None:
        profile_id = self.combo.currentData()
        if not profile_id:
            return None
        return next((p for p in self.ctx.config.proxies if p.id == profile_id), None)

    def _on_combo_changed(self, _index: int) -> None:
        profile = self._current_profile()
        if profile is None or profile.is_default:
            return
        for other in self.ctx.config.proxies:
            other.is_default = (other.id == profile.id)
        self.ctx.apply_config_changes()

    def _on_edit(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        ProxyCredentialsDialog(self.ctx, profile, self).exec()

    def _on_new(self) -> None:
        ProxyCredentialsDialog(self.ctx, None, self).exec()
