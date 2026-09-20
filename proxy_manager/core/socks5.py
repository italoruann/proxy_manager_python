"""Implementação mínima do protocolo SOCKS5 (RFC 1928/1929): lado servidor (para os apps locais)
e lado cliente (para falar com um proxy SOCKS5 upstream). Só o comando CONNECT é suportado."""
from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from typing import Optional

SOCKS_VERSION = 0x05

ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04

CMD_CONNECT = 0x01

REP_SUCCESS = 0x00
REP_GENERAL_FAILURE = 0x01
REP_NOT_ALLOWED = 0x02
REP_NETWORK_UNREACHABLE = 0x03
REP_HOST_UNREACHABLE = 0x04
REP_CONN_REFUSED = 0x05
REP_COMMAND_NOT_SUPPORTED = 0x07
REP_ADDR_TYPE_NOT_SUPPORTED = 0x08


class Socks5Error(Exception):
    pass


@dataclass
class Socks5Request:
    cmd: int
    host: str
    port: int
    atyp: int


async def server_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> Socks5Request:
    """Lê a saudação + o pedido CONNECT de um cliente SOCKS5 local. Não exige autenticação
    (o listener só escuta em loopback)."""
    header = await reader.readexactly(2)
    ver, nmethods = header[0], header[1]
    if ver != SOCKS_VERSION:
        raise Socks5Error(f"versão SOCKS não suportada: {ver}")
    await reader.readexactly(nmethods)  # métodos oferecidos, ignorados
    writer.write(bytes([SOCKS_VERSION, 0x00]))  # 0x00 = sem autenticação
    await writer.drain()

    req_header = await reader.readexactly(4)
    ver, cmd, _rsv, atyp = req_header
    if ver != SOCKS_VERSION:
        raise Socks5Error("versão inválida no request")

    if atyp == ATYP_IPV4:
        raw = await reader.readexactly(4)
        host = ".".join(str(b) for b in raw)
    elif atyp == ATYP_DOMAIN:
        length = (await reader.readexactly(1))[0]
        raw = await reader.readexactly(length)
        host = raw.decode("utf-8", errors="replace")
    elif atyp == ATYP_IPV6:
        raw = await reader.readexactly(16)
        host = ":".join(f"{raw[i]:02x}{raw[i+1]:02x}" for i in range(0, 16, 2))
    else:
        await send_server_reply(writer, REP_ADDR_TYPE_NOT_SUPPORTED)
        raise Socks5Error("tipo de endereço não suportado")

    port_bytes = await reader.readexactly(2)
    port = struct.unpack("!H", port_bytes)[0]

    if cmd != CMD_CONNECT:
        await send_server_reply(writer, REP_COMMAND_NOT_SUPPORTED)
        raise Socks5Error("apenas CONNECT é suportado")

    return Socks5Request(cmd=cmd, host=host, port=port, atyp=atyp)


async def send_server_reply(writer: asyncio.StreamWriter, rep: int,
                             bind_host: str = "0.0.0.0", bind_port: int = 0) -> None:
    addr_bytes = bytes(int(x) for x in bind_host.split(".")) if "." in bind_host else b"\x00\x00\x00\x00"
    packet = bytes([SOCKS_VERSION, rep, 0x00, ATYP_IPV4]) + addr_bytes + struct.pack("!H", bind_port)
    writer.write(packet)
    await writer.drain()


async def dial_upstream_socks5(host: str, port: int, target_host: str, target_port: int,
                                username: str = "", password: str = "",
                                timeout: float = 15.0) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Conecta a um proxy SOCKS5 upstream e abre um túnel CONNECT até o destino final."""
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        methods = bytes([0x00, 0x02]) if username else bytes([0x00])
        writer.write(bytes([SOCKS_VERSION, len(methods)]) + methods)
        await writer.drain()
        chosen = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
        if chosen[0] != SOCKS_VERSION:
            raise Socks5Error("proxy upstream respondeu versão inválida")
        method = chosen[1]

        if method == 0x02:
            uname = username.encode("utf-8")[:255]
            pwd = password.encode("utf-8")[:255]
            writer.write(bytes([0x01, len(uname)]) + uname + bytes([len(pwd)]) + pwd)
            await writer.drain()
            auth_resp = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            if auth_resp[1] != 0x00:
                raise Socks5Error("autenticação recusada pelo proxy upstream")
        elif method == 0xFF:
            raise Socks5Error("proxy upstream não aceitou nenhum método de autenticação")

        target_bytes = target_host.encode("utf-8")
        if len(target_bytes) > 255:
            raise Socks5Error("hostname de destino muito longo para SOCKS5")
        request = bytes([SOCKS_VERSION, CMD_CONNECT, 0x00, ATYP_DOMAIN, len(target_bytes)]) + \
            target_bytes + struct.pack("!H", target_port)
        writer.write(request)
        await writer.drain()

        reply_header = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        rep = reply_header[1]
        atyp = reply_header[3]
        if atyp == ATYP_IPV4:
            await reader.readexactly(4)
        elif atyp == ATYP_DOMAIN:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        elif atyp == ATYP_IPV6:
            await reader.readexactly(16)
        await reader.readexactly(2)

        if rep != REP_SUCCESS:
            raise Socks5Error(f"proxy upstream recusou a conexão (código {rep})")

        return reader, writer
    except Exception:
        writer.close()
        raise
