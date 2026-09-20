"""Ligar/desligar a inicialização automática do Proxy Manager junto com o sistema."""
from __future__ import annotations

import platform
import sys
from pathlib import Path

APP_ID = "ProxyManager"


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m proxy_manager --start-minimized'


def is_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
        return _is_enabled_windows()
    if system == "Linux":
        return _autostart_desktop_file().exists()
    return False


def set_enabled(enabled: bool) -> tuple[bool, str]:
    system = platform.system()
    if system == "Windows":
        return _set_windows(enabled)
    if system == "Linux":
        return _set_linux(enabled)
    return False, f"Início automático não suportado em {system}."


def _is_enabled_windows() -> bool:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except OSError:
        return False


def _set_windows(enabled: bool) -> tuple[bool, str]:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        return True, "Início automático atualizado."
    except OSError as exc:
        return False, f"Falha ao atualizar o registro: {exc}"


def _autostart_desktop_file() -> Path:
    return Path.home() / ".config" / "autostart" / "proxy-manager.desktop"


def _set_linux(enabled: bool) -> tuple[bool, str]:
    path = _autostart_desktop_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Proxy Manager\n"
            f"Exec={_launch_command()}\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        path.write_text(content, encoding="utf-8")
        return True, f"Início automático habilitado ({path})."
    if path.exists():
        path.unlink()
    return True, "Início automático desabilitado."
