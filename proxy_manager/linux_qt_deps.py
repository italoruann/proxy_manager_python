"""Garante, no Linux, as bibliotecas de sistema que o plugin xcb do Qt precisa.

As wheels do PySide6 trazem o Qt inteiro, mas o plugin xcb (X11/XWayland) depende de algumas libs
da distro que nem sempre vêm instaladas -- desde o Qt 6.5 a principal é a libxcb-cursor. Sem elas
o processo aborta com "Could not load the Qt platform plugin xcb" antes de abrir qualquer janela.
Aqui detectamos o que falta e instalamos pelo gerenciador de pacotes da distro, antes do
QApplication existir. Desative com PROXY_MANAGER_SKIP_DEPS=1.
"""
from __future__ import annotations

import ctypes.util
import os
import shutil
import subprocess
import sys

# Nome da lib (como o ctypes.util.find_library espera) -> pacote em cada gerenciador.
_REQUIRED_LIBS: dict[str, dict[str, str]] = {
    "xcb-cursor": {"pacman": "xcb-util-cursor", "apt": "libxcb-cursor0", "dnf": "xcb-util-cursor", "zypper": "libxcb-cursor0"},
    "xcb-icccm": {"pacman": "xcb-util-wm", "apt": "libxcb-icccm4", "dnf": "xcb-util-wm", "zypper": "libxcb-icccm4"},
    "xcb-keysyms": {"pacman": "xcb-util-keysyms", "apt": "libxcb-keysyms1", "dnf": "xcb-util-keysyms", "zypper": "libxcb-keysyms1"},
    "xcb-image": {"pacman": "xcb-util-image", "apt": "libxcb-image0", "dnf": "xcb-util-image", "zypper": "libxcb-image0"},
    "xcb-render-util": {"pacman": "xcb-util-renderutil", "apt": "libxcb-render-util0", "dnf": "xcb-util-renderutil", "zypper": "libxcb-render-util0"},
    "xkbcommon-x11": {"pacman": "libxkbcommon-x11", "apt": "libxkbcommon-x11-0", "dnf": "libxkbcommon-x11", "zypper": "libxkbcommon-x11-0"},
}

_INSTALL_CMDS: dict[str, list[str]] = {
    "pacman": ["pacman", "-S", "--needed", "--noconfirm"],
    "apt": ["apt-get", "install", "-y"],
    "dnf": ["dnf", "install", "-y"],
    "zypper": ["zypper", "--non-interactive", "install"],
}


def missing_libs() -> list[str]:
    return [lib for lib in _REQUIRED_LIBS if ctypes.util.find_library(lib) is None]


def detect_package_manager() -> str | None:
    for manager, binary in (("pacman", "pacman"), ("apt", "apt-get"), ("dnf", "dnf"), ("zypper", "zypper")):
        if shutil.which(binary):
            return manager
    return None


def install_command(manager: str, libs: list[str], *, is_root: bool, interactive: bool) -> list[str] | None:
    """Monta o comando de instalação, elevando com sudo (terminal) ou pkexec (sem terminal)."""
    packages = sorted({_REQUIRED_LIBS[lib][manager] for lib in libs})
    cmd = _INSTALL_CMDS[manager] + packages
    if is_root:
        return cmd
    if interactive and shutil.which("sudo"):
        return ["sudo", *cmd]
    if shutil.which("pkexec"):
        return ["pkexec", *cmd]
    return None


def _uses_xcb() -> bool:
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    # Vazio = o Qt escolhe sozinho e pode cair no xcb; "wayland;xcb" também pode chegar nele.
    return not platform or "xcb" in platform


def ensure_qt_system_libs() -> None:
    if not sys.platform.startswith("linux") or os.environ.get("PROXY_MANAGER_SKIP_DEPS") == "1":
        return
    if not _uses_xcb():
        return
    missing = missing_libs()
    if not missing:
        return

    manager = detect_package_manager()
    cmd = None
    if manager:
        cmd = install_command(manager, missing, is_root=os.geteuid() == 0, interactive=sys.stdin.isatty())

    if cmd:
        print(f"[proxy-manager] Faltam bibliotecas do Qt ({', '.join(missing)}). Instalando:", file=sys.stderr)
        print("  " + " ".join(cmd), file=sys.stderr)
        try:
            subprocess.run(cmd, check=False)
        except OSError as exc:
            print(f"[proxy-manager] Falha ao rodar o instalador: {exc}", file=sys.stderr)
        missing = missing_libs()
        if not missing:
            return

    print(
        f"[proxy-manager] Bibliotecas do Qt ainda ausentes: {', '.join(missing)}. "
        "Instale-as manualmente pelo gerenciador de pacotes da sua distro.",
        file=sys.stderr,
    )
    # Numa sessão Wayland dá para seguir sem o xcb, desde que ninguém tenha forçado a plataforma.
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        print("[proxy-manager] Usando o backend Wayland do Qt no lugar do xcb.", file=sys.stderr)
        os.environ["QT_QPA_PLATFORM"] = "wayland"
