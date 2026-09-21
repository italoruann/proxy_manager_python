"""Verifica o IP de saída real de um perfil de proxy, consultando o ip-api.com através do
próprio túnel do proxy — a única forma confiável de saber qual IP um site remoto de fato vê
quando a conexão passa por ele (o endereço configurado no perfil pode divergir do IP de saída em
proxies com pool de IPs, ex.: residenciais/rotativos)."""
from __future__ import annotations

import asyncio

from . import httpproxy, socks5
from .config import ProxyProfile

_CHECK_HOST = "ip-api.com"
_CHECK_PORT = 80
_CHECK_PATH = "/line/?fields=query"


async def fetch_egress_ip(profile: ProxyProfile, timeout: float = 8.0) -> str | None:
    """Abre um túnel através do proxy até o ip-api.com e devolve o IP de saída relatado, ou
    None se a verificação falhar (proxy fora do ar, timeout, resposta inesperada etc.). Nunca
    levanta exceção — falha na verificação não deve derrubar a conexão de verdade que a
    originou."""
    try:
        if profile.type == "socks5":
            reader, writer = await socks5.dial_upstream_socks5(
                profile.host, profile.port, _CHECK_HOST, _CHECK_PORT,
                profile.username, profile.password, timeout=timeout)
        else:
            reader, writer = await httpproxy.dial_upstream_http_connect(
                profile.host, profile.port, _CHECK_HOST, _CHECK_PORT,
                profile.username, profile.password, timeout=timeout)
    except Exception:
        return None

    try:
        # Depois do handshake (SOCKS5 CONNECT ou HTTP CONNECT), o túnel é um pipe TCP cru até o
        # ip-api.com — uma requisição HTTP de origem simples (sem forma absoluta) basta.
        request = (f"GET {_CHECK_PATH} HTTP/1.1\r\nHost: {_CHECK_HOST}\r\n"
                   f"Connection: close\r\n\r\n").encode("ascii")
        writer.write(request)
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(-1), timeout=timeout)
    except Exception:
        return None
    finally:
        writer.close()

    body = raw.split(b"\r\n\r\n", 1)[-1].decode("utf-8", errors="replace").strip()
    if not body:
        return None
    ip = body.splitlines()[-1].strip()
    return ip or None
