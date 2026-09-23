"""Identifica qual processo abriu uma conexão TCP local, cruzando a tabela de conexões do SO
(via psutil) com o endereço/porta observados pelo nosso listener."""
from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

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


def lookup_by_local_peer(peer_ip: str, peer_port: int, listen_port: int,
                         original_dst: Optional[tuple[str, int]] = None) -> ProcessInfo:
    """peer_ip/peer_port = endereço de origem visto pelo nosso servidor (o socket efêmero do
    processo cliente); listen_port = porta em que o nosso listener está escutando.

    `original_dst` só vem do modo transparente: lá o app discou o destino real e foi desviado
    pra cá por NAT (nftables/WinDivert) sem saber — o socket DELE continua registrado na tabela
    do SO com o destino original como endereço remoto, nunca com a nossa porta. Sem aceitar esse
    destino também, nenhum app era identificado no modo transparente (regras por app nunca
    batiam e tudo caía na ação padrão)."""
    try:
        conns = psutil.net_connections(kind="tcp")
    except (psutil.AccessDenied, PermissionError):
        return UNKNOWN

    own_pid = os.getpid()
    for c in conns:
        if not c.laddr or not c.raddr or not c.pid or c.pid == own_pid:
            continue
        if c.laddr.port != peer_port:
            continue
        if c.raddr.port == listen_port:
            return _resolve_process(c.pid)
        if (original_dst is not None and c.raddr.port == original_dst[1]
                and _same_ip(c.raddr.ip, original_dst[0])):
            return _resolve_process(c.pid)
    return UNKNOWN


def _same_ip(a: str, b: str) -> bool:
    # Sockets IPv6 dual-stack reportam destinos IPv4 como "::ffff:1.2.3.4".
    return a.removeprefix("::ffff:") == b.removeprefix("::ffff:")


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
