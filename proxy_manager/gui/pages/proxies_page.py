"""Página de Proxies: cadastro dos perfis (host, porta, usuário, senha) usados pelas regras."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ...core.config import ProxyProfile
from ..widgets.inputs import PasswordEdit
from ..workers import ProxyTestWorker


class ProxiesPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._current: ProxyProfile | None = None
        self._test_worker: ProxyTestWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel("Perfis de proxy")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Cadastre um ou mais proxies (SOCKS5 ou HTTP) para usar nas regras de roteamento.")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # -- lista à esquerda -------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        list_buttons = QHBoxLayout()
        new_btn = QPushButton("+ Novo perfil")
        new_btn.setObjectName("PrimaryButton")
        new_btn.clicked.connect(self._on_new)
        list_buttons.addWidget(new_btn)
        left_layout.addLayout(list_buttons)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.list_widget, 1)
        splitter.addWidget(left)

        # -- formulário à direita ----------------------------------------------
        right = QFrame()
        right.setObjectName("Card")
        form_layout = QVBoxLayout(right)
        form_layout.setContentsMargins(20, 18, 20, 18)
        form_layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItem("SOCKS5", "socks5")
        self.type_combo.addItem("HTTP / HTTPS (CONNECT)", "http")
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("ex.: proxy.minhaempresa.com")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(1080)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("(opcional)")
        self.password_edit = PasswordEdit()
        self.enabled_check = QCheckBox("Habilitado")
        self.enabled_check.setChecked(True)
        self.default_check = QCheckBox("Usar como proxy padrão (quando a regra não especificar um nome)")

        form.addRow("Nome", self.name_edit)
        form.addRow("Tipo", self.type_combo)
        form.addRow("Host", self.host_edit)
        form.addRow("Porta", self.port_spin)
        form.addRow("Usuário", self.user_edit)
        form.addRow("Senha", self.password_edit)
        form.addRow("", self.enabled_check)
        form.addRow("", self.default_check)
        form_layout.addLayout(form)

        self.test_result_label = QLabel("")
        self.test_result_label.setWordWrap(True)
        form_layout.addWidget(self.test_result_label)

        buttons_row = QHBoxLayout()
        self.save_btn = QPushButton("Salvar")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self._on_save)
        self.test_btn = QPushButton("Testar conexão")
        self.test_btn.clicked.connect(self._on_test)
        self.delete_btn = QPushButton("Remover")
        self.delete_btn.setObjectName("DangerButton")
        self.delete_btn.clicked.connect(self._on_delete)
        buttons_row.addWidget(self.save_btn)
        buttons_row.addWidget(self.test_btn)
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.delete_btn)
        form_layout.addLayout(buttons_row)
        form_layout.addStretch(1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._reload_list()
        self._set_form_enabled(False)

    # -- helpers -----------------------------------------------------------

    def _reload_list(self, select_id: str | None = None) -> None:
        # blockSignals só durante a reconstrução da lista; a seleção final é feita depois, com
        # sinais ligados, para que _on_selection_changed sincronize self._current corretamente.
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        target_item: QListWidgetItem | None = None
        for profile in self.ctx.config.proxies:
            label = f"{profile.name}"
            if profile.is_default:
                label += "  ★ padrão"
            if not profile.enabled:
                label += "  (desabilitado)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.list_widget.addItem(item)
            if select_id and profile.id == select_id:
                target_item = item
        self.list_widget.blockSignals(False)

        if target_item is not None:
            self.list_widget.setCurrentItem(target_item)
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self._current = None
            self._clear_form()
            self._set_form_enabled(False)

    def _set_form_enabled(self, enabled: bool) -> None:
        for widget in (self.name_edit, self.type_combo, self.host_edit, self.port_spin,
                       self.user_edit, self.password_edit, self.enabled_check, self.default_check,
                       self.save_btn, self.test_btn, self.delete_btn):
            widget.setEnabled(enabled)

    def _clear_form(self) -> None:
        self.name_edit.clear()
        self.host_edit.clear()
        self.port_spin.setValue(1080)
        self.user_edit.clear()
        self.password_edit.setText("")
        self.enabled_check.setChecked(True)
        self.default_check.setChecked(False)
        self.test_result_label.setText("")

    def _load_profile_into_form(self, profile: ProxyProfile) -> None:
        self.name_edit.setText(profile.name)
        index = self.type_combo.findData(profile.type)
        self.type_combo.setCurrentIndex(max(index, 0))
        self.host_edit.setText(profile.host)
        self.port_spin.setValue(profile.port)
        self.user_edit.setText(profile.username)
        self.password_edit.setText(profile.password)
        self.enabled_check.setChecked(profile.enabled)
        self.default_check.setChecked(profile.is_default)
        self.test_result_label.setText("")

    # -- eventos -----------------------------------------------------------

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._current = None
            self._clear_form()
            self._set_form_enabled(False)
            return
        profile_id = current.data(Qt.ItemDataRole.UserRole)
        profile = next((p for p in self.ctx.config.proxies if p.id == profile_id), None)
        if profile is None:
            return
        self._current = profile
        self._load_profile_into_form(profile)
        self._set_form_enabled(True)

    def _on_new(self) -> None:
        profile = ProxyProfile(name=f"Novo proxy {len(self.ctx.config.proxies) + 1}")
        if not self.ctx.config.proxies:
            profile.is_default = True
        self.ctx.config.proxies.append(profile)
        self.ctx.apply_config_changes()
        self._reload_list(select_id=profile.id)

    def _on_save(self) -> None:
        if self._current is None:
            return
        profile = self._current
        profile.name = self.name_edit.text().strip() or profile.name
        profile.type = self.type_combo.currentData()
        profile.host = self.host_edit.text().strip()
        profile.port = self.port_spin.value()
        profile.username = self.user_edit.text()
        profile.password = self.password_edit.text()
        profile.enabled = self.enabled_check.isChecked()
        profile.is_default = self.default_check.isChecked()

        if profile.is_default:
            for other in self.ctx.config.proxies:
                if other.id != profile.id:
                    other.is_default = False
        self.ctx.config.ensure_single_default()

        self.ctx.apply_config_changes()
        self._reload_list(select_id=profile.id)
        self.test_result_label.setText("Perfil salvo.")

    def _on_delete(self) -> None:
        if self._current is None:
            return
        confirm = QMessageBox.question(self, "Remover proxy",
                                        f"Remover o perfil '{self._current.name}'?\n"
                                        "Regras que apontam para ele passarão a usar o proxy padrão.")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.ctx.config.proxies = [p for p in self.ctx.config.proxies if p.id != self._current.id]
        self.ctx.config.ensure_single_default()
        self.ctx.apply_config_changes()
        self._reload_list()

    def _on_test(self) -> None:
        if self._current is None:
            return
        candidate = ProxyProfile(
            name=self.name_edit.text(), type=self.type_combo.currentData(),
            host=self.host_edit.text().strip(), port=self.port_spin.value(),
            username=self.user_edit.text(), password=self.password_edit.text(),
        )
        self.test_result_label.setText("Testando conexão…")
        self.test_btn.setEnabled(False)
        self._test_worker = ProxyTestWorker(candidate)
        self._test_worker.finished_test.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_finished(self, ok: bool, message: str) -> None:
        self.test_btn.setEnabled(True)
        prefix = "✔ " if ok else "✘ "
        self.test_result_label.setText(prefix + message)
