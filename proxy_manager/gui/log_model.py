"""Model de tabela (Qt) para o log de conexões, compartilhado entre o Dashboard (visão
resumida) e a página de Logs (visão completa e filtrável)."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..core.logstore import LogEntry
from .theme import PALETTE

COLUMNS = ["Hora", "Processo", "PID", "Destino", "IP", "Protocolo", "Regra", "Ação", "Proxy",
           "IP do Proxy", "Enviado", "Recebido", "Duração", "Status"]

# Papel próprio pra ordenação: DisplayRole é sempre uma string formatada ("1.2 KB", "230 ms",
# "01:04:59"), o que ordenaria por ordem alfabética em vez de numérica/cronológica. Colunas
# numéricas expõem aqui o valor bruto (int/float); as demais caem de volta pro texto exibido.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1

ACTION_LABELS = {"direct": "Direto", "proxy": "Via proxy", "block": "Bloqueado"}
STATUS_LABELS = {"ativa": "Em andamento", "concluida": "Concluída", "erro": "Erro", "bloqueada": "Bloqueada"}

_ACTION_COLOR = {
    "direct": PALETTE["success"],
    "proxy": PALETTE["accent_hover"],
    "block": PALETTE["danger"],
}
_STATUS_COLOR = {
    "ativa": PALETTE["warning"],
    "concluida": PALETTE["success"],
    "erro": PALETTE["danger"],
    "bloqueada": PALETTE["danger"],
}


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class LogTableModel(QAbstractTableModel):
    def __init__(self, max_rows: int = 5000, parent=None):
        super().__init__(parent)
        self._rows: list[LogEntry] = []
        self._index_by_id: dict[str, int] = {}
        self._max_rows = max_rows

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        entry = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(entry, col)
        if role == SORT_ROLE:
            return self._sort_value(entry, col)
        if role == Qt.ItemDataRole.ForegroundRole and col in (7, 13):
            color_map = _ACTION_COLOR if col == 7 else _STATUS_COLOR
            key = entry.action if col == 7 else entry.status
            color = color_map.get(key)
            if color:
                return QColor(color)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (2, 10, 11, 12):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and col == 6:
            return entry.matched_rule
        if role == Qt.ItemDataRole.ToolTipRole and col == 13 and entry.error:
            return entry.error
        return None

    @staticmethod
    def _display_value(entry: LogEntry, col: int):
        if col == 0:
            return datetime.datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        if col == 1:
            return entry.process_name or "desconhecido"
        if col == 2:
            return str(entry.pid) if entry.pid and entry.pid > 0 else "-"
        if col == 3:
            return f"{entry.dst_host}:{entry.dst_port}"
        if col == 4:
            return entry.dst_ip or ("resolvendo…" if entry.status == "ativa" else "-")
        if col == 5:
            return entry.protocol.upper()
        if col == 6:
            return entry.matched_rule
        if col == 7:
            return ACTION_LABELS.get(entry.action, entry.action)
        if col == 8:
            return entry.proxy_used or "-"
        if col == 9:
            if entry.action != "proxy":
                return "-"
            return entry.proxy_ip or ("resolvendo…" if entry.status == "ativa" else "-")
        if col == 10:
            return format_bytes(entry.bytes_sent)
        if col == 11:
            return format_bytes(entry.bytes_recv)
        if col == 12:
            return f"{entry.duration_ms} ms" if entry.status != "ativa" else "…"
        if col == 13:
            return STATUS_LABELS.get(entry.status, entry.status)
        return ""

    @staticmethod
    def _sort_value(entry: LogEntry, col: int):
        if col == 0:
            return entry.timestamp
        if col == 2:
            return entry.pid
        if col == 10:
            return entry.bytes_sent
        if col == 11:
            return entry.bytes_recv
        if col == 12:
            return entry.duration_ms
        return LogTableModel._display_value(entry, col)

    def entry_at(self, row: int) -> LogEntry | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def add_entries(self, entries: list[LogEntry]) -> None:
        """Insere várias entradas de uma vez (uma única volta de sinais Qt), para não travar a
        interface quando o motor gera muitas conexões em rajada."""
        if not entries:
            return
        self.beginInsertRows(QModelIndex(), 0, len(entries) - 1)
        self._rows[0:0] = list(reversed(entries))  # mais recente primeiro
        self.endInsertRows()
        self._reindex()

        overflow = len(self._rows) - self._max_rows
        if overflow > 0:
            start = len(self._rows) - overflow
            self.beginRemoveRows(QModelIndex(), start, len(self._rows) - 1)
            removed = self._rows[start:]
            del self._rows[start:]
            for entry in removed:
                self._index_by_id.pop(entry.id, None)
            self.endRemoveRows()

    def update_entries(self, entries: list[LogEntry]) -> None:
        for entry in entries:
            row = self._index_by_id.get(entry.id)
            if row is None:
                continue
            self._rows[row] = entry
            top_left = self.index(row, 0)
            bottom_right = self.index(row, len(COLUMNS) - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def _reindex(self) -> None:
        self._index_by_id = {e.id: i for i, e in enumerate(self._rows)}

    def clear(self) -> None:
        self.beginResetModel()
        self._rows = []
        self._index_by_id = {}
        self.endResetModel()

    def load_initial(self, entries: list[LogEntry]) -> None:
        self.beginResetModel()
        self._rows = list(entries)
        self._reindex()
        self.endResetModel()
