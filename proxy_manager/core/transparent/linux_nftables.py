"""Modo transparente no Linux: redireciona conexões TCP de saída para o listener transparente do
ProxyEngine via NAT (nftables) e recupera o destino original com SO_ORIGINAL_DST — a mesma
técnica usada por ferramentas como redsocks, só que com `nft` em vez de `iptables`. Cobre só
IPv4/TCP: UDP (necessário pra QUIC/HTTP3) fica fora do escopo desta fase, assim como já é no modo
explícito (SOCKS5 só suporta CONNECT) — por isso QUIC e TCP sobre IPv6 são rejeitados enquanto o
modo está ativo, forçando os apps a voltarem pro TCP/IPv4 que conseguimos interceptar.

Por que nft e não iptables: nftables é o backend nativo do firewalld e já vem instalado por
padrão em praticamente toda distro atual (inclusive Fedora, que vem tirando aos poucos o binário
`iptables` do conjunto padrão) — não precisa instalar nada a mais. Também é mais simples de
desfazer: nossas regras ficam isoladas numa tabela própria, registrada direto no hook `output`,
sem precisar inserir uma regra de jump numa chain embutida do sistema (como `iptables -A OUTPUT`
exigia) — então nunca interfere com as regras do firewalld/NetworkManager, e desligar é um único
comando (`nft delete table`) em vez de remover regra por regra.

Exige root (para alterar nftables) — start()/stop() nunca levantam exceção por falta de
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

TABLE_NAME = "proxymgr"
_SOL_IP = socket.SOL_IP if hasattr(socket, "SOL_IP") else 0
_SO_ORIGINAL_DST = 80  # Linux: não existe como constante em socket.* da stdlib


def is_supported() -> bool:
    return platform.system() == "Linux" and which("nft") is not None


def get_original_destination(writer: asyncio.StreamWriter) -> Optional[tuple[str, int]]:
    """Recupera o destino original de uma conexão redirecionada via NAT. O kernel guarda essa
    informação por conexão (via conntrack) e só a expõe no socket que efetivamente aceitou a
    conexão redirecionada — não dá pra descobrir de fora. Funciona igual não importa qual
    ferramenta (iptables ou nft) configurou a regra: é um recurso do conntrack do kernel."""
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


def _cmd_error(exc: Exception) -> str:
    stderr = getattr(exc, "stderr", None)
    if stderr:
        text = stderr.decode(errors="replace").strip() if isinstance(stderr, bytes) else str(stderr)
        if text:
            return text
    return str(exc)


def _delete_table_ignoring_errors() -> None:
    # "ip" é a família usada por versões antigas (só IPv4) — remove também, se tiver sobrado.
    for family in ("inet", "ip"):
        subprocess.run(["nft", "delete", "table", family, TABLE_NAME], capture_output=True, timeout=5)


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
                            "nftables). Rode o Proxy Manager com sudo/pkexec.")
        if which("nft") is None:
            # Fedora traz o nft por padrão; Ubuntu/Debian desktop geralmente não.
            return False, ("Comando 'nft' não encontrado. Instale o nftables (Ubuntu/Debian: "
                            "sudo apt install nftables; Fedora: sudo dnf install nftables).")

        # Se sobrou uma tabela de uma execução anterior que não terminou limpa (ex.: o processo
        # morreu sem chamar stop()), começa removendo ela — evita "table already exists".
        _delete_table_ignoring_errors()
        uid = str(os.geteuid())
        try:
            _run(["nft", "add", "table", "inet", TABLE_NAME])
            _run(["nft", "add", "chain", "inet", TABLE_NAME, "output",
                  "{", "type", "nat", "hook", "output", "priority", "-100", ";", "}"])
            # Nunca redireciona o próprio tráfego do Proxy Manager (evita loop: a conexão que ELE
            # mesmo abre até o destino real, ou até um proxy upstream, também passaria por aqui).
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "output",
                  "meta", "skuid", uid, "return"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "output",
                  "ip", "daddr", "127.0.0.0/8", "return"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "output",
                  "meta", "nfproto", "ipv4", "meta", "l4proto", "tcp",
                  "redirect", "to", f":{self.transparent_port}"])

            # Só sabemos interceptar TCP/IPv4. Sem isso, navegadores Chromium (Chrome, Edge,
            # Brave...) escapavam do proxy mesmo com a regra certa: depois da 1ª conexão eles
            # trocam pra QUIC (UDP 443) e, em redes com IPv6 (comum em qualquer distro), preferem
            # IPv6 — os dois passavam direto. Rejeitando na hora (em vez de descartar), o app cai
            # de imediato pro TCP/IPv4, que é redirecionado acima.
            _run(["nft", "add", "chain", "inet", TABLE_NAME, "block_unsupported",
                  "{", "type", "filter", "hook", "output", "priority", "0", ";", "}"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "block_unsupported",
                  "meta", "skuid", uid, "return"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "block_unsupported",
                  "oifname", "lo", "return"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "block_unsupported",
                  "udp", "dport", "443", "reject"])
            _run(["nft", "add", "rule", "inet", TABLE_NAME, "block_unsupported",
                  "meta", "nfproto", "ipv6", "meta", "l4proto", "tcp", "reject", "with", "tcp", "reset"])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            _delete_table_ignoring_errors()
            return False, f"Falha ao aplicar regras de nftables: {_cmd_error(exc)}"

        self._active = True
        return True, f"Modo transparente ativo — redirecionando TCP para 127.0.0.1:{self.transparent_port}."

    def stop(self) -> tuple[bool, str]:
        if not self._active:
            return True, "Modo transparente já estava desligado."
        try:
            _run(["nft", "delete", "table", "inet", TABLE_NAME])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            self._active = False
            return False, f"Modo transparente desligado com avisos (revise o nftables manualmente): {_cmd_error(exc)}"
        self._active = False
        return True, "Modo transparente desligado; tabela nftables removida."
