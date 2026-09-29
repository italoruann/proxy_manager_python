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
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("KDE_SESSION_VERSION", raising=False)


def _fake_gsettings(monkeypatch, persisted: bool):
    store: dict[str, str] = {}

    def fake_run(cmd, check=False, capture_output=False, timeout=None, input=None):
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
    def fake_run(cmd, check=False, capture_output=False, timeout=None, input=None):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"No such schema \"org.gnome.system.proxy\"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is False
    assert "No such schema" in message
    assert "gsettings-desktop-schemas" in message


def test_warns_that_chromium_ignores_system_proxy_on_xfce(monkeypatch):
    _fake_gsettings(monkeypatch, persisted=True)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is False
    assert f"--proxy-pac-url={PAC}" in message


def test_gnome_session_needs_no_browser_flag(monkeypatch):
    _fake_gsettings(monkeypatch, persisted=True)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is True
    assert "--proxy-pac-url" not in message


def test_env_script_exports_pac_for_chromium(tmp_path):
    path = mod._write_env_script(58091, PAC)
    assert f'export auto_proxy="{PAC}"' in path.read_text(encoding="utf-8")


def _fake_kde(monkeypatch, gsettings_persisted: bool = True):
    """Sem kwriteconfig: simula o cat/tee do kioslaverc em Python (roda em qualquer SO)."""
    gsettings: dict[str, str] = {}
    signals: list[list[str]] = []

    def fake_run(cmd, check=False, capture_output=False, timeout=None, input=None):
        if cmd[0] == "gsettings":
            if cmd[1] == "set":
                if gsettings_persisted:
                    gsettings[cmd[3]] = cmd[4]
                return _Done()
            return _Done(f"'{gsettings.get(cmd[3], '')}'\n")
        if cmd[0] == "sh":
            path = mod.Path(cmd[-1])
            return _Done(path.read_text(encoding="utf-8") if path.exists() else "")
        if cmd[0] == "tee":
            mod.Path(cmd[-1]).write_bytes(input)
            return _Done()
        if cmd[0] == "dbus-send":
            signals.append(cmd)
            return _Done()
        raise AssertionError(cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_has_binary", lambda name: name in ("gsettings", "dbus-send"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    return signals


def test_kde_without_kwriteconfig_writes_kioslaverc_directly(monkeypatch, tmp_path):
    (tmp_path / "kioslaverc").write_text(
        "[Other]\nfoo=bar\n\n[Proxy Settings]\nProxyType=0\nNoProxyFor=\n", encoding="utf-8")
    signals = _fake_kde(monkeypatch)

    ok, message = mod._apply_linux(PAC, 58091)

    assert ok is True
    assert "KDE/kioslaverc configurado" in message
    values = mod._parse_kioslaverc((tmp_path / "kioslaverc").read_text(encoding="utf-8"))
    assert values == {"ProxyType": "2", "NoProxyFor": "", "Proxy Config Script": PAC}
    assert "[Other]\nfoo=bar" in (tmp_path / "kioslaverc").read_text(encoding="utf-8")
    assert signals and "reparseSlaveConfiguration" in signals[0][4]


def test_kde_creates_kioslaverc_and_reverts(monkeypatch, tmp_path):
    _fake_kde(monkeypatch)
    mod._apply_linux(PAC, 58091)
    ok, message = mod._remove_linux()
    assert "KDE/kioslaverc revertido" in message
    assert mod._parse_kioslaverc((tmp_path / "kioslaverc").read_text(encoding="utf-8"))["ProxyType"] == "0"


def test_kde_warns_firefox_when_gsettings_not_persisted(monkeypatch):
    _fake_kde(monkeypatch, gsettings_persisted=False)
    ok, message = mod._apply_linux(PAC, 58091)
    assert ok is True  # o Chrome ainda pega pelo kioslaverc
    assert "Firefox" in message


def test_kde_detected_without_env_from_existing_kioslaverc(monkeypatch, tmp_path):
    (tmp_path / "kioslaverc").write_text("", encoding="utf-8")
    assert mod._kde_present() is True


def test_edit_kioslaverc_appends_group_when_missing():
    text = mod._edit_kioslaverc("[General]\na=1\n", {"ProxyType": "2"})
    assert text == "[General]\na=1\n\n[Proxy Settings]\nProxyType=2\n"
