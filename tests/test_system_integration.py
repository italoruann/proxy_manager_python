"""Testes da integração de proxy do sistema no Linux: mocka subprocess/which (nunca mexe no
gsettings de verdade) pra rodar em qualquer SO."""
import subprocess

import pytest

from proxy_manager.core import system_integration as mod

PAC = "http://127.0.0.1:58093/proxy.pac"


class _Done:
    def __init__(self, stdout: str = ""):
        self.returncode = 0
        self.stdout = stdout.encode()
        self.stderr = b""


@pytest.fixture(autouse=True)
def _only_gsettings(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_has_binary", lambda name: name == "gsettings")
    monkeypatch.setattr(mod, "_desktop_uid", lambda: None)
    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path)


def _fake_gsettings(monkeypatch, persisted: bool):
    store: dict[str, str] = {}

    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        if cmd[1] == "set":
            if persisted:
                store[cmd[3]] = cmd[4]
            return _Done()
        # backend em memória: um processo novo sempre relê o valor padrão
        defaults = {"mode": "none", "autoconfig-url": ""}
        return _Done(f"'{store.get(cmd[3], defaults[cmd[3]])}'\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)


def test_gsettings_configured_when_value_is_persisted(monkeypatch):
    _fake_gsettings(monkeypatch, persisted=True)
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is True
    assert "gsettings configurado" in message


def test_gsettings_memory_backend_is_reported_as_failure(monkeypatch):
    _fake_gsettings(monkeypatch, persisted=False)
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is False
    assert "dconf" in message


def test_gsettings_missing_schema_explains_fix(monkeypatch):
    def fake_run(cmd, check=False, capture_output=False, timeout=None):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"No such schema \"org.gnome.system.proxy\"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is False
    assert "No such schema" in message
    assert "gsettings-desktop-schemas" in message
