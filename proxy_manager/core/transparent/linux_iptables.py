"""Modo transparente no Linux: redireciona conexões TCP de saída para o listener transparente do
ProxyEngine via NAT (iptables REDIRECT) e recupera o destino original com SO_ORIGINAL_DST — a
mesma técnica usada por ferramentas como redsocks. Cobre só IPv4/TCP: UDP (necessário pra
QUIC/HTTP3) fica fora do escopo desta fase, assim como já é no modo explícito (SOCKS5 só suporta
CONNECT).

Exige root (para alterar iptables) — start()/stop() nunca levantam exceção por falta de
privilégio ou falha de comando; sempre retornam (ok, mensagem) pra GUI mostrar."""
from __future__ import annotations

import asyncio
import os
import platform
import socket
import struct
import subprocess
from shutil import which
from typing import Optional

CHAIN_NAME = "PROXYMGR_OUT"
_SOL_IP = socket.SOL_IP if hasattr(socket, "SOL_IP") else 0
_SO_ORIGINAL_DST = 80  # Linux: não existe como constante em socket.* da stdlib


def is_supported() -> bool:
    return platform.system() == "Linux" and which("iptables") is not None


def get_original_destination(writer: asyncio.StreamWriter) -> Optional[tuple[str, int]]:
    """Recupera o destino original de uma conexão redirecionada via REDIRECT/DNAT. O kernel
    guarda essa informação por conexão (via conntrack) e só a expõe no socket que efetivamente
    aceitou a conexão redirecionada — não dá pra descobrir de fora."""
    sock = writer.get_extra_info("socket")
    if sock is None:
        return None
    try:
        raw = sock.getsockopt(_SOL_IP, _SO_ORIGINAL_DST, 16)
    except OSError:
        return None
    port = struct.unpack("!H", raw[2:4])[0]
    host = socket.inet_ntoa(raw[4:8])
    return host, port


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=5)


def _rule_exists(check_cmd: list[str]) -> bool:
    result = subprocess.run(check_cmd, capture_output=True, timeout=5)
    return result.returncode == 0


def _cmd_error(exc: Exception) -> str:
    stderr = getattr(exc, "stderr", None)
    if stderr:
        text = stderr.decode(errors="replace").strip() if isinstance(stderr, bytes) else str(stderr)
        if text:
            return text
    return str(exc)


class LinuxTransparentMode:
    def __init__(self, transparent_port: int):
        self.transparent_port = transparent_port
        self._active = False

    def resolve_destination(self, writer: asyncio.StreamWriter, peer_port: int) -> Optional[tuple[str, int]]:
        """Interface comum com WindowsTransparentMode (que precisa de peer_port; aqui ele é
        ignorado porque o Linux já expõe o destino original diretamente no socket aceito)."""
        return get_original_destination(writer)

    def start(self) -> tuple[bool, str]:
        if os.geteuid() != 0:
            return False, ("Modo transparente no Linux exige privilégio de root (pra configurar "
                            "iptables). Rode o Proxy Manager com sudo.")
        try:
            # "Chain already exists" (rc=1) é esperado numa segunda ativação sem stop() limpo
            # antes (ex.: o processo anterior morreu sem chamar stop()) — ignorado de propósito.
            subprocess.run(["iptables", "-t", "nat", "-N", CHAIN_NAME], capture_output=True, timeout=5)

            _run(["iptables", "-t", "nat", "-F", CHAIN_NAME])
            # Nunca redireciona o próprio tráfego do Proxy Manager (evita loop: a conexão que
            # ELE mesmo abre até o destino real, ou até um proxy upstream, também passaria pela
            # OUTPUT chain se não fosse por esta regra).
            _run(["iptables", "-t", "nat", "-A", CHAIN_NAME, "-m", "owner",
                  "--uid-owner", str(os.geteuid()), "-j", "RETURN"])
            _run(["iptables", "-t", "nat", "-A", CHAIN_NAME, "-d", "127.0.0.0/8", "-j", "RETURN"])
            _run(["iptables", "-t", "nat", "-A", CHAIN_NAME, "-p", "tcp", "-j", "REDIRECT",
                  "--to-ports", str(self.transparent_port)])

            if not _rule_exists(["iptables", "-t", "nat", "-C", "OUTPUT", "-p", "tcp", "-j", CHAIN_NAME]):
                _run(["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-j", CHAIN_NAME])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            return False, f"Falha ao aplicar regras de iptables: {_cmd_error(exc)}"

        self._active = True
        return True, f"Modo transparente ativo — redirecionando TCP para 127.0.0.1:{self.transparent_port}."

    def stop(self) -> tuple[bool, str]:
        if not self._active:
            return True, "Modo transparente já estava desligado."

        warnings: list[str] = []
        for cmd in (
            ["iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp", "-j", CHAIN_NAME],
            ["iptables", "-t", "nat", "-F", CHAIN_NAME],
            ["iptables", "-t", "nat", "-X", CHAIN_NAME],
        ):
            try:
                _run(cmd)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
                warnings.append(_cmd_error(exc))

        self._active = False
        if warnings:
            return False, "Modo transparente desligado com avisos (revise o iptables manualmente): " + "; ".join(warnings)
        return True, "Modo transparente desligado; regras de iptables removidas."
