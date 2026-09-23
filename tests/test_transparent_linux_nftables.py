"""Testes do modo transparente no Linux: mocka subprocess (nunca roda nft de verdade) e um
socket falso (nunca precisa de uma conexão redirecionada de verdade) pra validar a lógica sem
precisar de root nem de estar rodando em Linux."""
import socket
import struct
import subprocess

import pytest

from proxy_manager.core.transparent import linux_nftables as mod
from proxy_manager.core.transparent.linux_nftables import LinuxTransparentMode, get_original_destination


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
    monkeypatch.setattr(mod, "which", lambda name: f"/usr/sbin/{name}")


@pytest.fixture()
def record_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_start_refuses_without_root(monkeypatch):
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000, raising=False)
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is False
    assert "root" in message.lower()


def test_start_applies_expected_nftables_rules(fake_root, record_commands):
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is True
    assert "58095" in message
    # a regra de redirect pra porta certa precisa ter sido aplicada
    redirect_calls = [c for c in record_commands if "redirect" in c]
    assert redirect_calls, "deveria ter aplicado uma regra de redirect"
    assert any(f":{58095}" in c for c in redirect_calls[0])
    # a exclusão do próprio tráfego (evita loop) precisa existir
    owner_calls = [c for c in record_commands if "skuid" in c]
    assert owner_calls, "deveria excluir o próprio uid do redirect pra evitar loop"
    # tudo isolado numa tabela própria (nunca mexe em OUTPUT/chains do sistema)
    assert all("OUTPUT" not in c for c in record_commands)


def test_stop_removes_table_and_is_idempotent(fake_root, record_commands):
    backend = LinuxTransparentMode(transparent_port=58095)
    backend.start()
    record_commands.clear()

    ok, message = backend.stop()
    assert ok is True
    assert record_commands == [["nft", "delete", "table", "ip", mod.TABLE_NAME]]

    # chamar stop() de novo sem um start() no meio não deve tentar rodar comandos de novo
    record_commands.clear()
    ok2, message2 = backend.stop()
    assert ok2 is True
    assert record_commands == []


def test_start_fails_gracefully_when_nft_errors(fake_root, monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        if check and "redirect" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"nft: Could not process rule: No such file or directory")
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    backend = LinuxTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is False
    assert "nftables" in message.lower() or "No such file" in message


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


def test_start_explains_how_to_install_nft_when_missing(fake_root, monkeypatch):
    monkeypatch.setattr(mod, "which", lambda name: None)
    ok, message = mod.LinuxTransparentMode(58095).start()
    assert ok is False
    assert "apt install nftables" in message
