"""Servidor HTTP proxy local (suporta CONNECT para HTTPS e requisições HTTP simples) e o
cliente usado para falar com um proxy HTTP upstream."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class HttpProxyError(Exception):
    pass


@dataclass
class HttpHead:
    first_line: str
    method: str
    target: str
    version: str
    headers: list[str] = field(default_factory=list)

    def header_value(self, name: str) -> str | None:
        name_l = name.lower() + ":"
        for h in self.headers:
            if h.lower().startswith(name_l):
                return h.split(":", 1)[1].strip()
        return None


async def read_request_head(reader: asyncio.StreamReader, timeout: float = 20.0) -> HttpHead:
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    text = raw.decode("iso-8859-1")
    lines = [l for l in text.split("\r\n") if l]
    if not lines:
        raise HttpProxyError("requisição HTTP vazia")
    parts = lines[0].split(" ", 2)
    if len(parts) != 3:
        raise HttpProxyError(f"linha de requisição inválida: {lines[0]!r}")
    method, target, version = parts
    return HttpHead(first_line=lines[0], method=method.upper(), target=target, version=version, headers=lines[1:])


def parse_target(head: HttpHead) -> tuple[str, int]:
    if head.method == "CONNECT":
        host, _, port_s = head.target.rpartition(":")
        if not host:
            raise HttpProxyError(f"alvo de CONNECT inválido: {head.target!r}")
        return host, int(port_s)

    if head.target.startswith("http://") or head.target.startswith("https://"):
        parsed = urlsplit(head.target)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.hostname or "", port

    host_header = head.header_value("Host") or ""
    if ":" in host_header:
        host, _, port_s = host_header.rpartition(":")
        return host, int(port_s)
    return host_header, 80


def origin_form_request(head: HttpHead) -> bytes:
    """Reescreve a linha de requisição em forma de origem (path apenas), para uso quando
    conectamos direto ao servidor de destino ou via túnel SOCKS5."""
    path = head.target
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlsplit(path)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
    request_line = f"{head.method} {path} {head.version}\r\n"
    kept_headers = [h for h in head.headers if not h.lower().startswith("proxy-connection:")]
    return (request_line + "\r\n".join(kept_headers) + "\r\n\r\n").encode("iso-8859-1")


def absolute_form_request(head: HttpHead, proxy_auth: str | None) -> bytes:
    """Mantém a forma absoluta original (como o cliente enviou), útil para repassar a um proxy
    HTTP upstream, adicionando Proxy-Authorization se necessário."""
    headers = list(head.headers)
    if proxy_auth:
        headers = [h for h in headers if not h.lower().startswith("proxy-authorization:")]
        headers.append(f"Proxy-Authorization: Basic {proxy_auth}")
    return (head.first_line + "\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("iso-8859-1")


def connect_request_line(target_host: str, target_port: int, proxy_auth: str | None) -> bytes:
    lines = [f"CONNECT {target_host}:{target_port} HTTP/1.1", f"Host: {target_host}:{target_port}"]
    if proxy_auth:
        lines.append(f"Proxy-Authorization: Basic {proxy_auth}")
    lines.append("Proxy-Connection: Keep-Alive")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1")


def basic_auth(username: str, password: str) -> str:
    return base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")


async def read_status_line(reader: asyncio.StreamReader, timeout: float = 20.0) -> tuple[int, str]:
    raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    text = raw.decode("iso-8859-1")
    first_line = text.split("\r\n", 1)[0]
    parts = first_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise HttpProxyError(f"resposta HTTP inválida: {first_line!r}")
    return int(parts[1]), (parts[2] if len(parts) > 2 else "")


async def dial_upstream_http_connect(host: str, port: int, target_host: str, target_port: int,
                                      username: str = "", password: str = "",
                                      timeout: float = 15.0) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        auth = basic_auth(username, password) if username else None
        writer.write(connect_request_line(target_host, target_port, auth))
        await writer.drain()
        status, reason = await read_status_line(reader, timeout=timeout)
        if status != 200:
            raise HttpProxyError(f"proxy upstream recusou CONNECT: {status} {reason}")
        return reader, writer
    except Exception:
        writer.close()
        raise
