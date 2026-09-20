"""Testes do autostart no Windows: mocka subprocess (nunca roda schtasks de verdade). Trocamos a
chave Run do registro por uma Tarefa Agendada com /RL HIGHEST porque o executável empacotado
pede elevação (UAC) sempre que abre — itens da chave Run sobem sem privilégio nenhum no login e
nunca conseguiriam iniciar um app que exige admin."""
import subprocess

from proxy_manager.core import autostart


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self.stdout = b""
        self.stderr = stderr


def test_is_enabled_queries_scheduled_task(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=False, timeout=None):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    assert autostart._is_enabled_windows() is True
    assert calls[0][:3] == ["schtasks", "/Query", "/TN"]


def test_is_enabled_returns_false_when_task_does_not_exist(monkeypatch):
    monkeypatch.setattr(autostart.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(1))
    assert autostart._is_enabled_windows() is False


def test_is_enabled_returns_false_when_schtasks_is_unavailable(monkeypatch):
    def raise_oserror(*a, **k):
        raise OSError("schtasks not found")

    monkeypatch.setattr(autostart.subprocess, "run", raise_oserror)
    assert autostart._is_enabled_windows() is False


def test_set_enabled_true_creates_task_with_highest_privilege(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=False, timeout=None):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    ok, message = autostart._set_windows(True)

    assert ok is True
    cmd = calls[0]
    assert cmd[:3] == ["schtasks", "/Create", "/TN"]
    assert "/RL" in cmd and cmd[cmd.index("/RL") + 1] == "HIGHEST"
    assert "/SC" in cmd and cmd[cmd.index("/SC") + 1] == "ONLOGON"


def test_set_enabled_false_deletes_task(monkeypatch):
    calls = []

    def fake_run(cmd, capture_output=False, timeout=None):
        calls.append(cmd)
        return _FakeCompletedProcess(0)

    monkeypatch.setattr(autostart.subprocess, "run", fake_run)
    ok, message = autostart._set_windows(False)

    assert ok is True
    assert calls[0][:3] == ["schtasks", "/Delete", "/TN"]


def test_set_enabled_false_is_ok_when_task_already_absent(monkeypatch):
    monkeypatch.setattr(autostart.subprocess, "run", lambda *a, **k: _FakeCompletedProcess(1))
    ok, message = autostart._set_windows(False)
    assert ok is True


def test_set_enabled_true_reports_failure(monkeypatch):
    monkeypatch.setattr(
        autostart.subprocess, "run",
        lambda *a, **k: _FakeCompletedProcess(1, stderr=b"ERRO: acesso negado."),
    )
    ok, message = autostart._set_windows(True)
    assert ok is False
    assert "acesso negado" in message.lower()


def test_set_enabled_true_handles_missing_schtasks(monkeypatch):
    def raise_oserror(*a, **k):
        raise OSError("schtasks not found")

    monkeypatch.setattr(autostart.subprocess, "run", raise_oserror)
    ok, message = autostart._set_windows(True)
    assert ok is False
