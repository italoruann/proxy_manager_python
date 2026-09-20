"""Página de Regras: uma seção de Aplicativos cadastrados (nome + caminho do executável) e,
logo abaixo, as Regras de roteamento propriamente ditas (quem e o quê vai direto, via proxy ou
bloqueado). Duas visões sincronizadas para as regras: uma tabela amigável e um editor de texto."""
from __future__ import annotations

import platform

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ...core.config import DEFAULT_RULES_TEXT, AppDefinition
from ...core.rules import Rule, RuleSet
from ..widgets.rules_highlighter import RulesHighlighter

COLUMN_LABELS = ["Ativo", "Aplicativos (vazio = qualquer um)", "Alvo (domínio/IP/CIDR, * = qualquer)", "Ação"]
APPS_COLUMN_LABELS = ["Nome", "Executável"]

DIGITAR_MANUALMENTE = "✎ Digitar manualmente…"


def _executable_filter() -> str:
    if platform.system() == "Windows":
        return "Executáveis (*.exe);;Todos os arquivos (*.*)"
    return "Todos os arquivos (*)"


class RulesPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        header_title = QLabel("Regras de roteamento")
        header_title.setObjectName("SectionTitle")
        root.addWidget(header_title)

        root.addWidget(self._build_apps_card())

        rules_title = QLabel("Regras")
        rules_title.setObjectName("SectionTitle")
        subtitle = QLabel("Avaliadas de cima para baixo — a primeira regra que casar com o "
                           "aplicativo e o destino define a ação.")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(rules_title)
        root.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_table_tab(), "Tabela")
        self.tabs.addTab(self._build_text_tab(), "Texto avançado")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self._load_from_config()
        self._reload_apps_table()

    # -- seção de aplicativos cadastrados --------------------------------------

    def _build_apps_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        title = QLabel("Aplicativos cadastrados")
        title.setObjectName("CardTitle")
        hint = QLabel("Cadastre aqui o nome e o executável dos programas que você vai usar nas "
                       "regras abaixo — evita ter que decorar o nome exato do processo.")
        hint.setObjectName("CardHint")
        hint.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(hint)

        form = QHBoxLayout()
        self.app_name_edit = QLineEdit()
        self.app_name_edit.setPlaceholderText("Nome (ex.: Chrome)")
        self.app_path_edit = QLineEdit()
        self.app_path_edit.setPlaceholderText("Caminho do executável")
        self.app_path_edit.setReadOnly(True)
        browse_btn = QPushButton("Procurar…")
        browse_btn.clicked.connect(self._on_browse_executable)
        self.add_app_def_btn = QPushButton("+ Adicionar")
        self.add_app_def_btn.setObjectName("PrimaryButton")
        self.add_app_def_btn.setEnabled(False)
        self.add_app_def_btn.setToolTip("Escolha um executável em \"Procurar…\" primeiro.")
        self.add_app_def_btn.clicked.connect(self._on_add_app_definition)
        # "Procurar..." só preenche os campos — sem isso, era fácil achar que já tinha
        # cadastrado o app e nunca ter clicado no botão que de fato salva.
        self.app_path_edit.textChanged.connect(
            lambda text: self.add_app_def_btn.setEnabled(bool(text.strip())))
        form.addWidget(self.app_name_edit, 1)
        form.addWidget(self.app_path_edit, 2)
        form.addWidget(browse_btn)
        form.addWidget(self.add_app_def_btn)
        layout.addLayout(form)

        self.apps_table = QTableWidget(0, len(APPS_COLUMN_LABELS))
        self.apps_table.setHorizontalHeaderLabels(APPS_COLUMN_LABELS)
        self.apps_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.apps_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.apps_table.verticalHeader().setVisible(False)
        self.apps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.apps_table.setMaximumHeight(160)
        layout.addWidget(self.apps_table)

        remove_row = QHBoxLayout()
        remove_row.addStretch(1)
        remove_btn = QPushButton("Remover selecionado")
        remove_btn.setObjectName("DangerButton")
        remove_btn.clicked.connect(self._on_remove_app_definition)
        remove_row.addWidget(remove_btn)
        layout.addLayout(remove_row)
        return card

    def _on_browse_executable(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar executável", "", _executable_filter())
        if not path:
            return
        self.app_path_edit.setText(path)
        if not self.app_name_edit.text().strip():
            guessed = AppDefinition(executable_path=path).process_name
            self.app_name_edit.setText(guessed.rsplit(".", 1)[0] if "." in guessed else guessed)

    def _on_add_app_definition(self) -> None:
        path = self.app_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Aplicativos", "Escolha o executável com \"Procurar…\" antes de adicionar.")
            return
        name = self.app_name_edit.text().strip() or AppDefinition(executable_path=path).process_name
        app_def = AppDefinition(name=name, executable_path=path)
        self.ctx.config.apps.append(app_def)

        created_rule = self._ensure_catchall_rule_for_app(app_def.process_name)

        self.ctx.apply_config_changes()
        self.app_name_edit.clear()
        self.app_path_edit.clear()
        self._reload_apps_table()
        self._refresh_rules_views()

        if created_rule:
            QMessageBox.information(
                self, "Aplicativos",
                f'"{app_def.name}" cadastrado. Como ainda não havia nenhuma regra para ele, criei '
                f"automaticamente: todo o tráfego de {app_def.process_name} vai pelo proxy padrão "
                "(igual ao Proxifier quando você só seleciona o app). Para refinar por site "
                "(ex.: deixar um site específico direto), edite essa regra na seção Regras — "
                "coloque as mais específicas ACIMA dela na lista."
            )

    def _ensure_catchall_rule_for_app(self, process_name: str) -> bool:
        """Se ainda não existir nenhuma regra para esse app, cria uma regra 'pega tudo' (alvo
        '*') pra ele, no fim da lista — replica o comportamento do Proxifier: só selecionar o
        app já basta para capturar todo o tráfego dele. Retorna True se criou uma regra nova."""
        if not process_name:
            return False
        rule_set = RuleSet.parse(self.ctx.config.rules_text)
        already_scoped = any(process_name.lower() in (a.lower() for a in r.apps) for r in rule_set.rules)
        if already_scoped:
            return False
        rule_set.rules.append(Rule(apps=[process_name], pattern="*", action="proxy"))
        self.ctx.config.rules_text = rule_set.to_text()
        return True

    def _refresh_rules_views(self) -> None:
        rule_set = RuleSet.parse(self.ctx.config.rules_text)
        self._populate_table(rule_set)
        self.text_edit.blockSignals(True)
        self.text_edit.setPlainText(self.ctx.config.rules_text)
        self.text_edit.blockSignals(False)

    def _on_remove_app_definition(self) -> None:
        row = self.apps_table.currentRow()
        if row < 0:
            return
        del self.ctx.config.apps[row]
        self.ctx.apply_config_changes()
        self._reload_apps_table()

    def _reload_apps_table(self) -> None:
        self.apps_table.setRowCount(0)
        for app in self.ctx.config.apps:
            row = self.apps_table.rowCount()
            self.apps_table.insertRow(row)
            self.apps_table.setItem(row, 0, QTableWidgetItem(app.name))
            self.apps_table.setItem(row, 1, QTableWidgetItem(app.executable_path))

    def _pick_app_process_name(self) -> str | None:
        """Usado pelo botão "+ App com proxy padrão": deixa escolher um app já cadastrado (pelo
        nome de processo extraído do executável) em vez de digitar na mão. Retorna None quando
        o usuário optou por digitar manualmente (ou cancelou), para não interferir no fluxo atual."""
        if not self.ctx.config.apps:
            return None
        options = [f"{a.name} ({a.process_name})" for a in self.ctx.config.apps] + [DIGITAR_MANUALMENTE]
        choice, ok = QInputDialog.getItem(self, "Escolher aplicativo", "Aplicativo cadastrado:",
                                           options, 0, False)
        if not ok or choice == DIGITAR_MANUALMENTE:
            return None
        index = options.index(choice)
        return self.ctx.config.apps[index].process_name

    # -- aba tabela ----------------------------------------------------------

    def _build_table_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.table = QTableWidget(0, len(COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, self.table.horizontalHeader().ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        add_btn = QPushButton("+ Adicionar regra")
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._on_add_row)
        add_app_btn = QPushButton("+ App com proxy padrão")
        add_app_btn.setToolTip(
            "Cria uma regra 'pega tudo' (alvo *) para um aplicativo específico — ideal para "
            "'todo o Chrome pelo proxy, sem precisar detalhar cada site'. Regras mais específicas "
            "para esse mesmo app, colocadas ACIMA dela na lista, continuam tendo prioridade."
        )
        add_app_btn.clicked.connect(self._on_add_app_catchall)
        dup_btn = QPushButton("Duplicar")
        dup_btn.clicked.connect(self._on_duplicate_row)
        remove_btn = QPushButton("Remover")
        remove_btn.setObjectName("DangerButton")
        remove_btn.clicked.connect(self._on_remove_row)
        up_btn = QPushButton("Mover ▲")
        up_btn.clicked.connect(lambda: self._on_move_row(-1))
        down_btn = QPushButton("Mover ▼")
        down_btn.clicked.connect(lambda: self._on_move_row(1))
        save_btn = QPushButton("Salvar alterações")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._on_save_table)

        buttons.addWidget(add_btn)
        buttons.addWidget(add_app_btn)
        buttons.addWidget(dup_btn)
        buttons.addWidget(remove_btn)
        buttons.addWidget(up_btn)
        buttons.addWidget(down_btn)
        buttons.addStretch(1)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)
        return tab

    def _make_action_combo(self, action_kind: str, proxy_name: str | None) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Proxy padrão", ("proxy", None))
        combo.addItem("Direto (sem proxy)", ("direct", None))
        combo.addItem("Bloquear", ("block", None))
        for profile in self.ctx.config.proxies:
            combo.addItem(f"Proxy: {profile.name}", ("proxy", profile.name))
        wanted = (action_kind, proxy_name if action_kind == "proxy" else None)
        for i in range(combo.count()):
            if combo.itemData(i) == wanted:
                combo.setCurrentIndex(i)
                break
        return combo

    def _insert_table_row(self, index: int, apps: str = "", pattern: str = "",
                           action_kind: str = "proxy", proxy_name: str | None = None,
                           enabled: bool = True) -> None:
        self.table.insertRow(index)
        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled |
                               Qt.ItemFlag.ItemIsSelectable)
        enabled_item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.table.setItem(index, 0, enabled_item)
        self.table.setItem(index, 1, QTableWidgetItem(apps))
        self.table.setItem(index, 2, QTableWidgetItem(pattern))
        self.table.setCellWidget(index, 3, self._make_action_combo(action_kind, proxy_name))

    def _row_data(self, row: int) -> dict:
        combo: QComboBox = self.table.cellWidget(row, 3)  # type: ignore[assignment]
        kind, proxy_name = combo.currentData()
        return {
            "enabled": self.table.item(row, 0).checkState() == Qt.CheckState.Checked,
            "apps": self.table.item(row, 1).text(),
            "pattern": self.table.item(row, 2).text(),
            "action_kind": kind,
            "proxy_name": proxy_name,
        }

    def _set_row_data(self, row: int, data: dict) -> None:
        self.table.item(row, 0).setCheckState(
            Qt.CheckState.Checked if data["enabled"] else Qt.CheckState.Unchecked)
        self.table.item(row, 1).setText(data["apps"])
        self.table.item(row, 2).setText(data["pattern"])
        self.table.setCellWidget(row, 3, self._make_action_combo(data["action_kind"], data["proxy_name"]))

    def _populate_table(self, rule_set: RuleSet) -> None:
        self.table.setRowCount(0)
        for rule in rule_set.rules:
            row = self.table.rowCount()
            self._insert_table_row(row, apps=", ".join(rule.apps), pattern=rule.pattern,
                                    action_kind=rule.action_kind, proxy_name=rule.proxy_name,
                                    enabled=rule.enabled)

    def _rule_set_from_table(self) -> RuleSet:
        rules: list[Rule] = []
        for row in range(self.table.rowCount()):
            data = self._row_data(row)
            pattern = data["pattern"].strip()
            if not pattern:
                continue
            apps = [a.strip() for a in data["apps"].split(",") if a.strip()]
            kind, proxy_name = data["action_kind"], data["proxy_name"]
            if kind == "proxy" and proxy_name:
                action = f"proxy:{proxy_name}"
            else:
                action = kind
            rules.append(Rule(apps=apps, pattern=pattern, action=action, enabled=data["enabled"]))
        return RuleSet(rules)

    def _on_add_row(self) -> None:
        self._insert_table_row(self.table.rowCount())

    def _on_add_app_catchall(self) -> None:
        """Atalho para o caso de uso mais comum: 'todo o tráfego deste app pelo proxy'. Equivale
        a escrever `apps: <app>` seguido de um alvo `*` no editor de texto, mas sem precisar
        conhecer essa sintaxe. Se já existir algum aplicativo cadastrado na seção acima, deixa
        escolher um deles (usa o nome de processo extraído do executável); senão, abre a célula
        para digitar manualmente."""
        process_name = self._pick_app_process_name()
        row = self.table.rowCount()
        self._insert_table_row(row, apps=process_name or "", pattern="*", action_kind="proxy")
        self.table.setCurrentCell(row, 1)
        if not process_name:
            self.table.editItem(self.table.item(row, 1))

    def _on_duplicate_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        data = self._row_data(row)
        self._insert_table_row(row + 1, apps=data["apps"], pattern=data["pattern"],
                                action_kind=data["action_kind"], proxy_name=data["proxy_name"],
                                enabled=data["enabled"])

    def _on_remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _on_move_row(self, direction: int) -> None:
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or not (0 <= target < self.table.rowCount()):
            return
        data_row = self._row_data(row)
        data_target = self._row_data(target)
        self._set_row_data(row, data_target)
        self._set_row_data(target, data_row)
        self.table.setCurrentCell(target, 0)

    def _on_save_table(self) -> None:
        rule_set = self._rule_set_from_table()
        self.ctx.config.rules_text = rule_set.to_text()
        self.ctx.apply_config_changes()
        self._refresh_rules_views()
        QMessageBox.information(self, "Regras", "Regras salvas e aplicadas ao motor.")

    # -- aba texto -------------------------------------------------------------

    def _build_text_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        help_label = QLabel(
            "Sintaxe: <code>apps: proc1.exe, proc2</code> define o escopo das linhas seguintes "
            "(<code>apps: *</code> volta a valer para todos). Cada regra é "
            "<code>padrao.dominio.com [+direct|+block|+proxy:nome]</code>; sem sufixo, "
            "usa o proxy padrão. Prefixe com <code>!</code> para desabilitar uma regra sem apagá-la."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("CardHint")
        layout.addWidget(help_label)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setObjectName("RulesEditor")
        self._highlighter = RulesHighlighter(self.text_edit.document())
        layout.addWidget(self.text_edit, 1)

        buttons = QHBoxLayout()
        apply_btn = QPushButton("Aplicar")
        apply_btn.setObjectName("PrimaryButton")
        apply_btn.clicked.connect(self._on_apply_text)
        reset_btn = QPushButton("Restaurar exemplo")
        reset_btn.clicked.connect(self._on_reset_text)
        buttons.addWidget(apply_btn)
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return tab

    def _on_apply_text(self) -> None:
        text = self.text_edit.toPlainText()
        rule_set = RuleSet.parse(text)
        self.ctx.config.rules_text = text
        self.ctx.apply_config_changes()
        self._populate_table(rule_set)
        QMessageBox.information(self, "Regras", f"{len(rule_set.rules)} regra(s) aplicadas ao motor.")

    def _on_reset_text(self) -> None:
        self.text_edit.setPlainText(DEFAULT_RULES_TEXT)

    # -- sincronização geral ----------------------------------------------------

    def _load_from_config(self) -> None:
        rule_set = RuleSet.parse(self.ctx.config.rules_text)
        self._populate_table(rule_set)
        self.text_edit.setPlainText(self.ctx.config.rules_text)

    def _on_tab_changed(self, _index: int) -> None:
        pass
