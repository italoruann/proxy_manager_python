"""Integração com o SO: gera o PAC file que aponta tudo para os nossos listeners locais, serve
esse PAC via HTTP, e aplica/remove essa configuração como proxy do sistema (Windows e Linux)."""
from __future__ import annotations

import asyncio
import os
import platform
import subprocess
from pathlib import Path
from typing import Callable

from .config import data_dir

PacProvider = Callable[[], str]


def build_pac_script(socks_port: int, http_port: int) -> str:
    """Sempre manda tudo para o nosso proxy local: é o nosso motor de regras (não o PAC) quem
    decide depois se a conexão vai direto, bloqueada ou por um proxy upstream. Isso garante que
    TODA conexão apareça no log, inclusive as que acabam indo direto."""
    return f"""\
function FindProxyForURL(url, host) {{
    return "PROXY 127.0.0.1:{http_port}; SOCKS5 127.0.0.1:{socks_port}; DIRECT";
}}
"""


async def start_pac_server(pac_provider: PacProvider, port: int) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except Exception:
            writer.close()
            return
        body = pac_provider().encode("utf-8")
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/x-ns-proxy-autoconfig\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + body
        )
        try:
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


def pac_url(pac_port: int) -> str:
    return f"http://127.0.0.1:{pac_port}/proxy.pac"


# ---------------------------------------------------------------------------
# Aplicação da configuração de proxy do sistema
# ---------------------------------------------------------------------------

def apply_system_proxy(url: str, http_port: int) -> tuple[bool, str]:
    system = platform.system()
    if system == "Windows":
        return _apply_windows(url)
    if system == "Linux":
        return _apply_linux(url, http_port)
    return False, f"Sistema operacional não suportado para integração automática: {system}"


def remove_system_proxy() -> tuple[bool, str]:
    system = platform.system()
    if system == "Windows":
        return _remove_windows()
    if system == "Linux":
        return _remove_linux()
    return False, f"Sistema operacional não suportado para integração automática: {system}"


def _apply_windows(url: str) -> tuple[bool, str]:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, url)
        _notify_windows_settings_changed()
        return True, "Proxy automático (PAC) configurado no Windows."
    except OSError as exc:
        return False, f"Falha ao configurar o registro do Windows: {exc}"


def _remove_windows() -> tuple[bool, str]:
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass
        _notify_windows_settings_changed()
        return True, "Configuração de proxy do Windows removida."
    except OSError as exc:
        return False, f"Falha ao remover configuração do Windows: {exc}"


def _notify_windows_settings_changed() -> None:
    try:
        import ctypes
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        wininet = ctypes.windll.Wininet  # type: ignore[attr-defined]
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except Exception:
        pass


# Plasma 6 (Arch, Fedora 40+, ...) só traz o kwriteconfig6; Plasma 5 só o kwriteconfig5.
_KWRITECONFIG_BINARIES = ("kwriteconfig6", "kwriteconfig5")


def _apply_linux(url: str, http_port: int) -> tuple[bool, str]:
    messages: list[str] = []
    ok_any = False

    if _has_binary("gsettings"):
        try:
            _run_as_desktop_user(["gsettings", "set", "org.gnome.system.proxy", "mode", "auto"])
            _run_as_desktop_user(["gsettings", "set", "org.gnome.system.proxy", "autoconfig-url", url])
            messages.append("GNOME/gsettings configurado.")
            ok_any = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            messages.append(f"gsettings falhou: {exc}")

    kwriteconfig = _find_kwriteconfig()
    if kwriteconfig:
        try:
            _run_as_desktop_user([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings",
                                  "--key", "ProxyType", "2"])
            _run_as_desktop_user([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings",
                                  "--key", "Proxy Config Script", url])
            messages.append("KDE/kioslaverc configurado.")
            ok_any = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            messages.append(f"{kwriteconfig} falhou: {exc}")

    env_path = _write_env_script(http_port)
    messages.append(f"Script de variáveis de ambiente gerado em {env_path} (use 'source' para apps de terminal).")

    if not ok_any:
        messages.append(
            "Nenhum ambiente gráfico suportado automaticamente foi detectado; "
            "configure manualmente a URL do PAC acima nas configurações de rede do seu desktop."
        )
    return ok_any, " ".join(messages)


def _remove_linux() -> tuple[bool, str]:
    messages: list[str] = []
    if _has_binary("gsettings"):
        try:
            _run_as_desktop_user(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"])
            messages.append("GNOME/gsettings revertido para 'sem proxy'.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            messages.append(f"gsettings falhou: {exc}")
    kwriteconfig = _find_kwriteconfig()
    if kwriteconfig:
        try:
            _run_as_desktop_user([kwriteconfig, "--file", "kioslaverc", "--group", "Proxy Settings",
                                  "--key", "ProxyType", "0"])
            messages.append("KDE/kioslaverc revertido.")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            messages.append(f"{kwriteconfig} falhou: {exc}")
    return True, " ".join(messages) if messages else "Nenhuma alteração de sistema para reverter."


def _find_kwriteconfig() -> str | None:
    return next((name for name in _KWRITECONFIG_BINARIES if _has_binary(name)), None)


def _desktop_uid() -> int | None:
    """UID do usuário dono da sessão gráfica quando estamos rodando elevados (pkexec/sudo), ou
    None quando já rodamos como o próprio usuário."""
    if os.geteuid() != 0:
        return None
    for var in ("PKEXEC_UID", "SUDO_UID"):
        value = os.environ.get(var, "")
        if value.isdigit() and int(value) != 0:
            return int(value)
    return None


def _run_as_desktop_user(cmd: list[str]) -> None:
    """gsettings/kwriteconfig gravam na config do usuário que os executa. Elevado via pkexec
    (necessário pro modo transparente), isso configurava o proxy do ROOT — o Chrome e o resto da
    sessão do usuário nunca viam a mudança. Aqui rodamos como o usuário de verdade, apontando pro
    barramento D-Bus da sessão dele (o gsettings grava via dconf, que depende dele)."""
    uid = _desktop_uid()
    if uid is not None:
        import pwd
        user = pwd.getpwuid(uid)
        cmd = ["runuser", "-u", user.pw_name, "--", "env",
               f"HOME={user.pw_dir}", f"XDG_RUNTIME_DIR=/run/user/{uid}",
               f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus", *cmd]
    subprocess.run(cmd, check=True, capture_output=True, timeout=5)


def _write_env_script(http_port: int) -> Path:
    path = data_dir() / "env.sh"
    # As variáveis de ambiente não suportam PAC; usamos o proxy HTTP local diretamente.
    # O roteamento por domínio/app continua sendo decidido pelo nosso motor de regras.
    proxy_addr = f"http://127.0.0.1:{http_port}"
    content = (
        "# Gerado pelo Proxy Manager — source este arquivo para que ferramentas de terminal\n"
        "# (curl, wget, git, etc.) passem pelo Proxy Manager.\n"
        f'export http_proxy="{proxy_addr}"\n'
        f'export https_proxy="{proxy_addr}"\n'
        f'export HTTP_PROXY="{proxy_addr}"\n'
        f'export HTTPS_PROXY="{proxy_addr}"\n'
        'export no_proxy="localhost,127.0.0.1"\n'
    )
    path.write_text(content, encoding="utf-8")
    return path


def _has_binary(name: str) -> bool:
    from shutil import which
    return which(name) is not None
