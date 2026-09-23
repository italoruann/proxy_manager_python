"""Testes do cache de processos: garantem que um PID reciclado pelo SO para outro processo não
continua devolvendo o nome/caminho do processo antigo (a cache não tinha nenhuma forma de saber
que o processo original já tinha morrido)."""
from types import SimpleNamespace

import psutil
import pytest

from proxy_manager.core import process_lookup


@pytest.fixture(autouse=True)
def _clear_cache():
    process_lookup.clear_cache()
    yield
    process_lookup.clear_cache()


def _fake_process(name: str, exe: str, create_time: float):
    return SimpleNamespace(name=lambda: name, exe=lambda: exe, create_time=lambda: create_time)


def test_stale_cache_entry_is_replaced_when_pid_is_reused(monkeypatch):
    calls = iter([
        _fake_process("old.exe", "/bin/old.exe", create_time=100.0),  # resolução original
        _fake_process("old.exe", "/bin/old.exe", create_time=100.0),  # confirma create_time (cache hit)
        _fake_process("new.exe", "/bin/new.exe", create_time=200.0),  # create_time mudou: checagem de identidade
        _fake_process("new.exe", "/bin/new.exe", create_time=200.0),  # resolução do processo novo
    ])
    monkeypatch.setattr(process_lookup.psutil, "Process", lambda pid: next(calls))

    first = process_lookup._resolve_process(pid=4242)
    assert first.name == "old.exe"

    second = process_lookup._resolve_process(pid=4242)
    assert second.name == "old.exe"  # ainda em cache, mesmo processo (create_time bateu)

    third = process_lookup._resolve_process(pid=4242)
    assert third.name == "new.exe"  # PID reciclado: create_time não bate mais


def test_cache_is_bounded_lru(monkeypatch):
    monkeypatch.setattr(process_lookup, "_MAX_CACHE_ENTRIES", 3)
    monkeypatch.setattr(
        process_lookup.psutil, "Process",
        lambda pid: _fake_process(f"proc{pid}.exe", f"/bin/proc{pid}.exe", create_time=float(pid)),
    )

    for pid in range(1, 6):
        process_lookup._resolve_process(pid)

    assert len(process_lookup._process_cache) == 3
    assert set(process_lookup._process_cache.keys()) == {3, 4, 5}


def test_failed_lookup_is_not_cached(monkeypatch):
    def _raise(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(process_lookup.psutil, "Process", _raise)

    info = process_lookup._resolve_process(pid=999)
    assert info.name == "pid 999"
    assert 999 not in process_lookup._process_cache


def _conn(lport, rip, rport, pid):
    return SimpleNamespace(laddr=SimpleNamespace(ip="192.168.0.5", port=lport),
                           raddr=SimpleNamespace(ip=rip, port=rport), pid=pid)


def test_transparent_lookup_matches_client_socket_by_original_destination(monkeypatch):
    # No modo transparente o socket do app continua apontando pro destino original (o NAT é
    # invisível pra ele), não pra nossa porta transparente.
    conns = [
        _conn(58095, "192.168.0.5", 40000, pid=process_lookup.os.getpid()),  # nosso lado aceito
        _conn(40000, "142.250.1.1", 443, pid=777),  # socket do Chrome
    ]
    monkeypatch.setattr(process_lookup.psutil, "net_connections", lambda kind: conns)
    monkeypatch.setattr(process_lookup, "_resolve_process",
                        lambda pid: process_lookup.ProcessInfo(pid=pid, name="chrome"))

    info = process_lookup.lookup_by_local_peer("192.168.0.5", 40000, 58095,
                                               original_dst=("142.250.1.1", 443))
    assert info.pid == 777

    assert process_lookup.lookup_by_local_peer("192.168.0.5", 40000, 58095) is process_lookup.UNKNOWN
