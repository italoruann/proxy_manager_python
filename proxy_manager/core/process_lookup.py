"""Identifica qual processo abriu uma conexão TCP local, cruzando a tabela de conexões do SO
(via psutil) com o endereço/porta observados pelo nosso listener."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import psutil

# Guardamos o create_time() junto com o ProcessInfo: é o jeito do psutil de detectar quando um
# PID foi reciclado pelo SO para um processo novo (senão a cache devolveria para sempre o
# nome/caminho do processo antigo que já morreu). Limitamos o tamanho (LRU) porque o motor roda
# indefinidamente e nunca teríamos outro gatilho para descartar entradas de PIDs que já se foram.
_MAX_CACHE_ENTRIES = 512
_process_cache: "OrderedDict[int, tuple[float, ProcessInfo]]" = OrderedDict()


@dataclass
class ProcessInfo:
    pid: int = -1
    name: str = "desconhecido"
    path: str = ""


UNKNOWN = ProcessInfo()


def lookup_by_local_peer(peer_ip: str, peer_port: int, listen_port: int) -> ProcessInfo:
    """peer_ip/peer_port = endereço de origem visto pelo nosso servidor (o socket efêmero do
    processo cliente); listen_port = porta em que o nosso listener está escutando."""
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError):
        return UNKNOWN

    for c in conns:
        if not c.laddr or not c.raddr:
            continue
        if c.laddr.port == peer_port and c.raddr.port == listen_port and c.pid:
            return _resolve_process(c.pid)
    return UNKNOWN


def _resolve_process(pid: int) -> ProcessInfo:
    cached = _process_cache.get(pid)
    if cached is not None:
        cached_create_time, info = cached
        try:
            still_same_process = psutil.Process(pid).create_time() == cached_create_time
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            still_same_process = False
        if still_same_process:
            _process_cache.move_to_end(pid)
            return info
        _process_cache.pop(pid, None)  # PID reciclado pelo SO para outro processo

    try:
        proc = psutil.Process(pid)
        create_time = proc.create_time()
        info = ProcessInfo(pid=pid, name=proc.name(), path=_safe_exe(proc))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # Não cacheamos essa falha: pode ser um processo que já morreu entre o accept() e esta
        # resolução, e não queremos travar "desconhecido" para sempre num PID que o SO reutilize.
        return ProcessInfo(pid=pid, name=f"pid {pid}", path="")

    _process_cache[pid] = (create_time, info)
    _process_cache.move_to_end(pid)
    if len(_process_cache) > _MAX_CACHE_ENTRIES:
        _process_cache.popitem(last=False)
    return info


def _safe_exe(proc: "psutil.Process") -> str:
    try:
        return proc.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        return ""


def clear_cache() -> None:
    _process_cache.clear()
