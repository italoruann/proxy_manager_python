"""Armazena e persiste o log de conexões. Desacoplado de Qt: notifica observadores via
callbacks simples; a camada de GUI é quem faz a ponte para sinais Qt (thread-safe)."""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .config import data_dir

EventCallback = Callable[[str, "LogEntry"], None]  # (evento "added"|"updated", entry)


@dataclass
class LogEntry:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    pid: int = -1
    process_name: str = ""
    process_path: str = ""
    protocol: str = ""  # "socks5" | "http"
    dst_host: str = ""
    dst_ip: str = ""
    dst_port: int = 0
    matched_rule: str = ""
    action: str = ""  # "direct" | "block" | "proxy"
    proxy_used: str = ""
    bytes_sent: int = 0
    bytes_recv: int = 0
    duration_ms: int = 0
    status: str = "ativa"  # "ativa" | "concluida" | "erro" | "bloqueada"
    error: str = ""


class LogStore:
    def __init__(self, retention_days: int = 14, max_memory_entries: int = 5000):
        self._lock = threading.Lock()
        self._entries: dict[str, LogEntry] = {}
        self._order: deque[str] = deque(maxlen=max_memory_entries)
        self._callbacks: list[EventCallback] = []
        self.retention_days = retention_days
        self._db_path = data_dir() / "connections.db"
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    id TEXT PRIMARY KEY,
                    timestamp REAL,
                    pid INTEGER,
                    process_name TEXT,
                    process_path TEXT,
                    protocol TEXT,
                    dst_host TEXT,
                    dst_ip TEXT,
                    dst_port INTEGER,
                    matched_rule TEXT,
                    action TEXT,
                    proxy_used TEXT,
                    bytes_sent INTEGER,
                    bytes_recv INTEGER,
                    duration_ms INTEGER,
                    status TEXT,
                    error TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_connections_ts ON connections(timestamp)")
            # Migração pra bancos criados antes do campo dst_ip existir: CREATE TABLE IF NOT
            # EXISTS não adiciona coluna em tabela já existente.
            existing_cols = {row[1] for row in con.execute("PRAGMA table_info(connections)")}
            if "dst_ip" not in existing_cols:
                con.execute("ALTER TABLE connections ADD COLUMN dst_ip TEXT DEFAULT ''")
        self._prune_old()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=5)

    def _prune_old(self) -> None:
        cutoff = time.time() - (self.retention_days * 86400)
        try:
            with self._connect() as con:
                con.execute("DELETE FROM connections WHERE timestamp < ?", (cutoff,))
        except sqlite3.Error:
            pass

    def subscribe(self, callback: EventCallback) -> None:
        with self._lock:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _notify(self, event: str, entry: LogEntry) -> None:
        for cb in list(self._callbacks):
            try:
                cb(event, entry)
            except Exception:
                pass

    def add(self, entry: LogEntry) -> LogEntry:
        with self._lock:
            evicted: Optional[str] = None
            if len(self._order) == self._order.maxlen:
                evicted = self._order[0]  # será descartado pelo append abaixo (deque com maxlen)
            self._entries[entry.id] = entry
            self._order.append(entry.id)
            if evicted is not None:
                self._entries.pop(evicted, None)
        self._notify("added", entry)
        return entry

    def update(self, entry_id: str, **changes) -> Optional[LogEntry]:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return None
            for k, v in changes.items():
                setattr(entry, k, v)
        self._notify("updated", entry)
        if entry.status in ("concluida", "erro", "bloqueada"):
            self._persist(entry)
        return entry

    def _persist(self, entry: LogEntry) -> None:
        try:
            with self._connect() as con:
                # Colunas nomeadas explicitamente (em vez de posicionais): bancos migrados via
                # ALTER TABLE ADD COLUMN (ver _init_db) têm a coluna nova no fim da tabela, não
                # na posição em que ela aparece no CREATE TABLE / dataclass.
                con.execute(
                    """INSERT OR REPLACE INTO connections
                    (id, timestamp, pid, process_name, process_path, protocol, dst_host, dst_ip,
                     dst_port, matched_rule, action, proxy_used, bytes_sent, bytes_recv,
                     duration_ms, status, error)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (entry.id, entry.timestamp, entry.pid, entry.process_name, entry.process_path,
                     entry.protocol, entry.dst_host, entry.dst_ip, entry.dst_port, entry.matched_rule,
                     entry.action, entry.proxy_used, entry.bytes_sent, entry.bytes_recv,
                     entry.duration_ms, entry.status, entry.error),
                )
        except sqlite3.Error:
            pass

    def recent(self, limit: int = 500) -> list[LogEntry]:
        with self._lock:
            ids = list(self._order)[-limit:]
            return [self._entries[i] for i in ids if i in self._entries]

    def query_history(self, limit: int = 1000) -> list[LogEntry]:
        try:
            with self._connect() as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT * FROM connections ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
                return [LogEntry(**dict(row)) for row in rows]
        except sqlite3.Error:
            return []

    def clear_memory(self) -> None:
        with self._lock:
            self._entries.clear()
            self._order.clear()

    def clear_persisted(self) -> None:
        try:
            with self._connect() as con:
                con.execute("DELETE FROM connections")
        except sqlite3.Error:
            pass
