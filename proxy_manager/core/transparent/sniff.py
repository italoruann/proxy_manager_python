"""No modo transparente não existe CONNECT nem cabeçalho Host explícito — o aplicativo acha que
está falando direto com o destino, então só enxergamos um IP:porta (via SO_ORIGINAL_DST no Linux
ou a tabela de NAT no Windows). Isso já basta para regras por IP/CIDR, mas quebraria regras por
domínio (`*.paypal.com`) sem um jeito de descobrir o hostname pretendido.

Este módulo espia passivamente os primeiros bytes que o cliente manda — o SNI do ClientHello TLS
(porta 443) ou o cabeçalho Host de uma requisição HTTP em texto puro (porta 80) — sem terminar a
conexão nem alterar nada: os mesmos bytes lidos aqui são sempre repassados ao destino real depois,
intactos, como prefixo do túnel."""
from __future__ import annotations

import struct
from typing import Optional

TLS_HANDSHAKE_RECORD = 0x16
TLS_CLIENT_HELLO = 0x01
TLS_EXTENSION_SERVER_NAME = 0x0000
SNI_HOST_NAME_TYPE = 0x00


def extract_sni(data: bytes) -> Optional[str]:
    """Extrai o SNI de um ClientHello TLS a partir dos bytes já recebidos. Retorna None se não
    for reconhecível como ClientHello, se o SNI não estiver presente, ou se os bytes disponíveis
    ainda não cobrirem a extensão inteira (ClientHello fragmentado em mais de um segmento TCP —
    caso raro, já que costuma caber num único pacote)."""
    try:
        return _extract_sni(data)
    except (struct.error, IndexError):
        return None


def _extract_sni(data: bytes) -> Optional[str]:
    if len(data) < 5 or data[0] != TLS_HANDSHAKE_RECORD:
        return None
    pos = 5  # pula o record header: tipo (1) + versão (2) + tamanho (2)
    if pos >= len(data) or data[pos] != TLS_CLIENT_HELLO:
        return None
    pos += 4  # handshake header: tipo (1) + tamanho (3)
    pos += 2 + 32  # client_version (2) + random (32)

    session_id_len = data[pos]
    pos += 1 + session_id_len

    cipher_suites_len = struct.unpack("!H", data[pos:pos + 2])[0]
    pos += 2 + cipher_suites_len

    compression_len = data[pos]
    pos += 1 + compression_len

    if pos + 2 > len(data):
        return None  # sem extensões (ou dados incompletos) — sem SNI pra achar
    extensions_len = struct.unpack("!H", data[pos:pos + 2])[0]
    pos += 2
    extensions_end = min(pos + extensions_len, len(data))

    while pos + 4 <= extensions_end:
        ext_type, ext_len = struct.unpack("!HH", data[pos:pos + 4])
        pos += 4
        if pos + ext_len > len(data):
            return None  # extensão cortada: ClientHello ainda incompleto
        if ext_type == TLS_EXTENSION_SERVER_NAME:
            return _parse_server_name_extension(data[pos:pos + ext_len])
        pos += ext_len
    return None


def _parse_server_name_extension(payload: bytes) -> Optional[str]:
    if len(payload) < 2:
        return None
    list_len = struct.unpack("!H", payload[0:2])[0]
    pos = 2
    end = min(2 + list_len, len(payload))
    while pos + 3 <= end:
        name_type = payload[pos]
        name_len = struct.unpack("!H", payload[pos + 1:pos + 3])[0]
        pos += 3
        if pos + name_len > len(payload):
            return None
        if name_type == SNI_HOST_NAME_TYPE:
            # O SNI já chega em ASCII/punycode (RFC 6066) — não precisa (e nem dá: o codec
            # "idna" do Python só aceita errors="strict") de decodificação IDNA aqui.
            return payload[pos:pos + name_len].decode("ascii", errors="replace")
        pos += name_len
    return None


def extract_http_host(data: bytes) -> Optional[str]:
    """Extrai o header Host de uma requisição HTTP em texto puro, se os cabeçalhos completos já
    estiverem nos bytes recebidos (procura o terminador \\r\\n\\r\\n)."""
    if b"\r\n\r\n" not in data:
        return None
    try:
        head = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
    except UnicodeDecodeError:
        return None
    for line in head.split("\r\n")[1:]:
        if line.lower().startswith("host:"):
            host = line.split(":", 1)[1].strip()
            if host.count(":") == 1:  # "host:porta" (host IPv6 vem entre colchetes, sem contar)
                host = host.rsplit(":", 1)[0]
            return host or None
    return None
