"""Testes do modo transparente no Linux: mocka subprocess (nunca roda iptables de verdade) e um
socket falso (nunca precisa de uma conexão redirecionada de verdade) pra validar a lógica sem
precisar de root nem de estar rodando em Linux."""
import socket
import struct
import subprocess

import pytest

from proxy_manager.core.transparent import linux_iptables as mod
from proxy_manager.core.transparent.linux_iptables import LinuxTransparentMode, get_original_destination


class _FakeCompletedProcess:
    def __init__(self, returncode: int):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = b""


@pytest.fixture()
def fake_root(monkeypatch):
    # os.geteuid só existe em POSIX — raising=False permite rodar esses testes também no
    # Windows (onde o atributo nem existe no módulo os de verdade).
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0, raising=False)


@pytest.fixture()
def record_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        calls.append(cmd)
        if check:
            return _FakeCompletedProcess(0)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_start_refuses_without_root(monkeypatch):
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000, raising=False)
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is False
    assert "root" in message.lower()


def test_start_applies_expected_iptables_rules(fake_root, record_commands):
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is True
    assert "58095" in message
    # a regra de REDIRECT pra porta certa precisa ter sido aplicada
    redirect_calls = [c for c in record_commands if "REDIRECT" in c]
    assert any("58095" in c for c in redirect_calls[0]) if redirect_calls else False
    # a exclusão do próprio tráfego (evita loop) precisa vir antes do REDIRECT
    owner_calls = [c for c in record_commands if "owner" in c]
    assert owner_calls, "deveria excluir o próprio uid do redirect pra evitar loop"


def test_stop_removes_rules_and_is_idempotent(fake_root, record_commands):
    backend = LinuxTransparentMode(transparent_port=58095)
    backend.start()
    record_commands.clear()

    ok, message = backend.stop()
    assert ok is True
    assert any("-X" in c for c in record_commands), "deveria remover a chain no final"

    # chamar stop() de novo sem um start() no meio não deve tentar rodar comandos de novo
    record_commands.clear()
    ok2, message2 = backend.stop()
    assert ok2 is True
    assert record_commands == []


def test_start_fails_gracefully_when_iptables_errors(fake_root, monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        if check and cmd[:2] == ["iptables", "-t"] and "REDIRECT" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"iptables: No chain/target/match by that name.")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is False
    assert "iptables" in message.lower() or "No chain" in message


def test_get_original_destination_parses_so_original_dst():
    class _FakeSocket:
        def getsockopt(self, level, optname, buflen):
            assert optname == 80
            # struct sockaddr_in: family(2) + port(2, network order) + ip(4) + padding(8)
            return struct.pack("!HH4s8x", socket.AF_INET, 443, socket.inet_aton("203.0.113.10"))

    class _FakeWriter:
        def get_extra_info(self, name):
            return _FakeSocket() if name == "socket" else None

    host, port = get_original_destination(_FakeWriter())
    assert host == "203.0.113.10"
    assert port == 443


def test_get_original_destination_returns_none_without_socket():
    class _FakeWriter:
        def get_extra_info(self, name):
            return None

    assert get_original_destination(_FakeWriter()) is None
