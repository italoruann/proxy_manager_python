"""Testes da checagem de libs do Qt no Linux: mocka find_library/subprocess (nunca instala nada)."""
from proxy_manager import linux_qt_deps as deps


def test_install_command_maps_packages_per_manager(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    cmd = deps.install_command("pacman", ["xcb-cursor", "xcb-icccm"], is_root=False, interactive=True)
    assert cmd == ["sudo", "pacman", "-S", "--needed", "--noconfirm", "xcb-util-cursor", "xcb-util-wm"]

    cmd = deps.install_command("apt", ["xcb-cursor"], is_root=True, interactive=False)
    assert cmd == ["apt-get", "install", "-y", "libxcb-cursor0"]


def test_install_command_uses_pkexec_without_terminal(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    cmd = deps.install_command("dnf", ["xcb-cursor"], is_root=False, interactive=False)
    assert cmd[0] == "pkexec"


def test_ensure_installs_missing_libs(monkeypatch):
    installed = set()
    calls = []
    monkeypatch.setattr(deps.sys, "platform", "linux")
    monkeypatch.delenv("PROXY_MANAGER_SKIP_DEPS", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(deps.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(deps.shutil, "which", lambda name: "/usr/bin/pacman" if name == "pacman" else None)
    monkeypatch.setattr(
        deps.ctypes.util, "find_library", lambda lib: f"lib{lib}.so" if lib != "xcb-cursor" or installed else None
    )

    def fake_run(cmd, check=False):
        calls.append(cmd)
        installed.add("xcb-cursor")

    monkeypatch.setattr(deps.subprocess, "run", fake_run)
    deps.ensure_qt_system_libs()
    assert calls == [["pacman", "-S", "--needed", "--noconfirm", "xcb-util-cursor"]]


def test_ensure_skips_when_platform_is_not_xcb(monkeypatch):
    monkeypatch.setattr(deps.sys, "platform", "linux")
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland")
    monkeypatch.setattr(deps, "missing_libs", lambda: (_ for _ in ()).throw(AssertionError("não deveria checar")))
    deps.ensure_qt_system_libs()
