"""Página de Logs: visão completa e filtrável de todas as conexões vistas pelo motor — o
objetivo principal do usuário é conseguir confirmar, com dados reais, que o proxy está sendo
usado (ou não) para cada destino/aplicativo."""
from __future__ import annotations

import csv

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ..app_context import AppContext
from ..log_model import ACTION_LABELS, COLUMNS, SORT_ROLE, LogTableModel


class LogFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._action = "all"
        self._protocol = "all"

    def lessThan(self, left, right) -> bool:  # noqa: N802
        # DisplayRole é sempre string formatada ("1.2 KB", "230 ms") — ordenar por ela daria
        # ordem alfabética em vez de numérica. SORT_ROLE expõe o valor bruto pras colunas que
        # precisam disso (Hora, PID, Enviado, Recebido, Duração).
        left_value = self.sourceModel().data(left, SORT_ROLE)
        right_value = self.sourceModel().data(right, SORT_ROLE)
        try:
            return left_value < right_value
        except TypeError:
            return str(left_value) < str(right_value)

    def set_text_filter(self, text: str) -> None:
        self._text = text.strip().lower()
        self.invalidateRowsFilter()

    def set_action_filter(self, action: str) -> None:
        self._action = action
        self.invalidateRowsFilter()

    def set_protocol_filter(self, protocol: str) -> None:
        self._protocol = protocol
        self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:  # noqa: N802
        model: LogTableModel = self.sourceModel()  # type: ignore[assignment]
        entry = model.entry_at(source_row)
        if entry is None:
            return False
        if self._action != "all" and entry.action != self._action:
            return False
        if self._protocol != "all" and entry.protocol != self._protocol:
            return False
        if self._text:
            haystack = f"{entry.process_name} {entry.process_path} {entry.dst_host} {entry.dst_ip} " \
                       f"{entry.matched_rule} {entry.proxy_used}".lower()
            if self._text not in haystack:
                return False
        return True


class LogsPage(QWidget):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel("Logs de conexão")
        title.setObjectName("SectionTitle")
        subtitle = QLabel("Toda conexão observada pelo motor aparece aqui — inclusive as que forem diretas.")
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Buscar por processo, destino, regra ou proxy…")
        self.search_edit.textChanged.connect(self._on_search_changed)

        self.action_combo = QComboBox()
        self.action_combo.addItem("Todas as ações", "all")
        for key, label in ACTION_LABELS.items():
            self.action_combo.addItem(label, key)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("Todos os protocolos", "all")
        self.protocol_combo.addItem("SOCKS5", "socks5")
        self.protocol_combo.addItem("HTTP/HTTPS", "http")
        self.protocol_combo.currentIndexChanged.connect(self._on_protocol_changed)

        self.autoscroll_check = QCheckBox("Rolar automaticamente")
        self.autoscroll_check.setChecked(True)

        clear_btn = QPushButton("Limpar")
        clear_btn.clicked.connect(self._on_clear)
        export_btn = QPushButton("Exportar CSV")
        export_btn.clicked.connect(self._on_export)

        filter_bar.addWidget(self.search_edit, 1)
        filter_bar.addWidget(self.action_combo)
        filter_bar.addWidget(self.protocol_combo)
        filter_bar.addWidget(self.autoscroll_check)
        filter_bar.addWidget(clear_btn)
        filter_bar.addWidget(export_btn)
        root.addLayout(filter_bar)

        self.model = ctx.log_model
        self.proxy_model = LogFilterProxy()
        self.proxy_model.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy_model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setSortingEnabled(True)
        # Ordem inicial: mais recente primeiro (igual ao comportamento de sempre, antes de
        # ordenação existir) — clicar em qualquer cabeçalho de coluna troca pra ela, e clicar de
        # novo inverte crescente/decrescente.
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        root.addWidget(self.table, 1)

        self.count_label = QLabel()
        self.count_label.setObjectName("CardHint")
        root.addWidget(self.count_label)
        self._update_count_label()

        ctx.log_added.connect(self._on_log_added)
        ctx.log_updated.connect(self._on_log_updated)

    # -- filtros -----------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self.proxy_model.set_text_filter(text)
        self._update_count_label()

    def _on_action_changed(self, _index: int) -> None:
        self.proxy_model.set_action_filter(self.action_combo.currentData())
        self._update_count_label()

    def _on_protocol_changed(self, _index: int) -> None:
        self.proxy_model.set_protocol_filter(self.protocol_combo.currentData())
        self._update_count_label()

    # -- eventos ao vivo -----------------------------------------------------

    def _on_log_added(self, _entries: list) -> None:
        # o AppContext já inseriu as entradas no model compartilhado; aqui só tratamos efeitos da UI.
        self._update_count_label()
        if self.autoscroll_check.isChecked():
            self.table.scrollToTop()

    def _on_log_updated(self, _entries: list) -> None:
        pass

    def _update_count_label(self) -> None:
        total = self.model.rowCount()
        visible = self.proxy_model.rowCount()
        if visible == total:
            self.count_label.setText(f"{total} conexões")
        else:
            self.count_label.setText(f"{visible} de {total} conexões (filtradas)")

    # -- ações -----------------------------------------------------------------

    def _on_clear(self) -> None:
        confirm = QMessageBox.question(self, "Limpar logs",
                                        "Limpar a lista de conexões exibida nesta sessão?\n"
                                        "(o histórico salvo em disco não é apagado)")
        if confirm == QMessageBox.StandardButton.Yes:
            self.model.clear()
            self.ctx.log_store.clear_memory()
            self._update_count_label()

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar logs", "conexoes.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            for row in range(self.proxy_model.rowCount()):
                values = []
                for col in range(len(COLUMNS)):
                    idx = self.proxy_model.index(row, col)
                    values.append(self.proxy_model.data(idx, Qt.ItemDataRole.DisplayRole))
                writer.writerow(values)
        QMessageBox.information(self, "Exportar logs", f"Logs exportados para:\n{path}")
