"""Ligar/desligar a inicialização automática do Proxy Manager junto com o sistema."""
from __future__ import annotations

import platform
import subprocess
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
        result = subprocess.run(["schtasks", "/Query", "/TN", APP_ID], capture_output=True, timeout=5)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _set_windows(enabled: bool) -> tuple[bool, str]:
    # Usa o Agendador de Tarefas (schtasks /RL HIGHEST), não a chave Run do registro: itens da
    # chave Run sobem sem privilégio nenhum no login, e o executável empacotado pede elevação
    # (UAC) sempre que é aberto — na chave Run ele simplesmente nunca conseguiria iniciar sozinho.
    try:
        if enabled:
            result = subprocess.run(
                ["schtasks", "/Create", "/TN", APP_ID, "/TR", _launch_command(),
                 "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"],
                capture_output=True, timeout=5,
            )
        else:
            result = subprocess.run(["schtasks", "/Delete", "/TN", APP_ID, "/F"],
                                     capture_output=True, timeout=5)
            if result.returncode != 0:
                return True, "Início automático já estava desabilitado."

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            return False, f"Falha ao atualizar a tarefa agendada: {stderr}"
        return True, "Início automático atualizado (tarefa agendada, roda elevado no login)."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Falha ao atualizar a tarefa agendada: {exc}"


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
