"""Testes do parser de SNI (TLS ClientHello) e do peek de Host (HTTP) usados pelo modo
transparente pra descobrir o domínio pretendido sem terminar a conexão."""
import struct

from proxy_manager.core.transparent.sniff import extract_http_host, extract_sni


def _build_client_hello(hostname: str | None) -> bytes:
    """Monta um ClientHello TLS 1.2 minimamente válido, com (ou sem) a extensão SNI, seguindo a
    mesma estrutura que extract_sni() espera — não precisa ser criptograficamente real."""
    extensions = b""
    if hostname is not None:
        name_bytes = hostname.encode("idna")
        server_name_entry = bytes([0x00]) + struct.pack("!H", len(name_bytes)) + name_bytes
        server_name_list = struct.pack("!H", len(server_name_entry)) + server_name_entry
        sni_extension = struct.pack("!HH", 0x0000, len(server_name_list)) + server_name_list
        extensions += sni_extension

    body = b""
    body += b"\x03\x03"  # client_version (TLS 1.2)
    body += b"\x00" * 32  # random
    body += bytes([0])  # session_id vazio
    body += struct.pack("!H", 2) + b"\x00\x2f"  # 1 cipher suite
    body += bytes([1]) + b"\x00"  # 1 compression method (null)
    body += struct.pack("!H", len(extensions)) + extensions

    handshake = bytes([0x01]) + len(body).to_bytes(3, "big") + body
    record = bytes([0x16]) + b"\x03\x01" + struct.pack("!H", len(handshake)) + handshake
    return record


def test_extract_sni_from_valid_client_hello():
    hello = _build_client_hello("www.paypal.com")
    assert extract_sni(hello) == "www.paypal.com"


def test_extract_sni_returns_none_when_extension_absent():
    hello = _build_client_hello(None)
    assert extract_sni(hello) is None


def test_extract_sni_returns_none_for_garbage_bytes():
    assert extract_sni(b"nao e nem perto de um client hello") is None
    assert extract_sni(b"") is None


def test_extract_sni_returns_none_for_truncated_client_hello():
    hello = _build_client_hello("www.paypal.com")
    assert extract_sni(hello[:20]) is None


def test_extract_http_host_from_plain_request():
    request = b"GET / HTTP/1.1\r\nHost: www.example.com\r\nUser-Agent: teste\r\n\r\n"
    assert extract_http_host(request) == "www.example.com"


def test_extract_http_host_strips_port():
    request = b"GET / HTTP/1.1\r\nHost: www.example.com:8080\r\n\r\n"
    assert extract_http_host(request) == "www.example.com"


def test_extract_http_host_returns_none_when_headers_incomplete():
    request = b"GET / HTTP/1.1\r\nHost: www.example.com"
    assert extract_http_host(request) is None


def test_extract_http_host_returns_none_when_header_missing():
    request = b"GET / HTTP/1.1\r\nUser-Agent: teste\r\n\r\n"
    assert extract_http_host(request) is None
