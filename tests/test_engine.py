"""Testes de integração do motor: sobe o engine de verdade em loopback e usa clientes reais
(HTTP e SOCKS5) para confirmar que o roteamento (direto/bloqueado/via proxy) e o log funcionam."""
import asyncio
import time

from proxy_manager.core.config import AppConfig, ProxyProfile, Settings
from proxy_manager.core.engine import ProxyEngine
from proxy_manager.core.logstore import LogStore
from proxy_manager.core.socks5 import (
    REP_HOST_UNREACHABLE,
    REP_SUCCESS,
    dial_upstream_socks5,
    send_server_reply,
    server_handshake,
)

SOCKS_PORT = 58380
HTTP_PORT = 58381
PAC_PORT = 58390


async def _start_target_server(body: bytes):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except Exception:
            writer.close()
            return
        resp = (b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() +
                b"\r\nConnection: close\r\n\r\n" + body)
        writer.write(resp)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def _make_engine(rules_text: str, default_action: str = "block",
                  proxies: list[ProxyProfile] | None = None) -> tuple[ProxyEngine, LogStore]:
    settings = Settings(socks_port=SOCKS_PORT, http_port=HTTP_PORT, pac_port=PAC_PORT,
                         default_action=default_action)
    cfg = AppConfig(proxies=proxies or [], rules_text=rules_text, settings=settings)
    store = LogStore(retention_days=1)
    return ProxyEngine(cfg, store), store


async def _start_fake_upstream_socks5_proxy():
    """Um proxy SOCKS5 "de verdade", mínimo, usando nosso próprio código de handshake —
    para testar ponta-a-ponta o caminho '+proxy' do motor (client -> engine -> este proxy
    upstream -> destino), sem precisar de um proxy externo real."""
    async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = await server_handshake(reader, writer)
        except Exception:
            writer.close()
            return
        try:
            target_reader, target_writer = await asyncio.open_connection(req.host, req.port)
        except OSError:
            await send_server_reply(writer, REP_HOST_UNREACHABLE)
            writer.close()
            return
        await send_server_reply(writer, REP_SUCCESS)
        await asyncio.gather(pump(reader, target_writer), pump(target_reader, writer))

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def test_direct_http_relay_and_log():
    async def scenario():
        target_server, target_port = await _start_target_server(b"ola mundo")
        engine, store = _make_engine(f"127.0.0.1 +direct\n")
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", HTTP_PORT)
            req = (f"GET http://127.0.0.1:{target_port}/ HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n").encode()
            writer.write(req)
            await writer.drain()
            data = await reader.read(-1)
            assert b"ola mundo" in data

            await asyncio.sleep(0.2)
            entries = store.recent()
            assert any(e.action == "direct" and e.status == "concluida" for e in entries)
        finally:
            engine.stop()
            target_server.close()

    asyncio.run(scenario())


def test_block_rule_returns_403():
    async def scenario():
        engine, store = _make_engine("127.0.0.1 +block\n")
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", HTTP_PORT)
            req = b"GET http://127.0.0.1:9/ HTTP/1.1\r\nHost: 127.0.0.1:9\r\nConnection: close\r\n\r\n"
            writer.write(req)
            await writer.drain()
            data = await reader.read(-1)
            assert b"403" in data

            await asyncio.sleep(0.2)
            entries = store.recent()
            assert any(e.action == "block" and e.status == "bloqueada" for e in entries)
        finally:
            engine.stop()

    asyncio.run(scenario())


def test_socks5_direct_relay():
    async def scenario():
        target_server, target_port = await _start_target_server(b"via socks5")
        engine, _store = _make_engine("127.0.0.1 +direct\n")
        engine.start()
        try:
            reader, writer = await dial_upstream_socks5("127.0.0.1", SOCKS_PORT, "127.0.0.1", target_port)
            req = (f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n").encode()
            writer.write(req)
            await writer.drain()
            data = await reader.read(-1)
            assert b"via socks5" in data
        finally:
            engine.stop()
            target_server.close()

    asyncio.run(scenario())


def test_relay_via_upstream_proxy_and_byte_counters():
    """Cobre o caminho '+proxy' (client -> engine -> proxy upstream -> destino) e confirma que
    os contadores de bytes por categoria (via proxy x direto) batem com a realidade."""
    async def scenario():
        target_server, target_port = await _start_target_server(b"resposta via proxy upstream")
        proxy_server, proxy_port = await _start_fake_upstream_socks5_proxy()
        profile = ProxyProfile(name="upstream-teste", type="socks5", host="127.0.0.1",
                                port=proxy_port, is_default=True)
        engine, store = _make_engine("127.0.0.1\n", proxies=[profile])  # sem sufixo => via proxy
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", HTTP_PORT)
            req = (f"GET http://127.0.0.1:{target_port}/ HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n").encode()
            writer.write(req)
            await writer.drain()
            data = await reader.read(-1)
            assert b"resposta via proxy upstream" in data

            await asyncio.sleep(0.2)
            entries = store.recent()
            assert any(e.action == "proxy" and e.proxy_used == "upstream-teste" and
                       e.status == "concluida" for e in entries)

            # A requisição GET (sem corpo) já é escrita no upstream antes do _pipe() começar;
            # é a resposta que flui inteiramente pelo _pipe(), então é ela que confirma a
            # contagem por categoria.
            assert engine.proxy_bytes_recv > 0
            assert engine.direct_bytes_sent == 0
            assert engine.direct_bytes_recv == 0
        finally:
            engine.stop()
            target_server.close()
            proxy_server.close()

    asyncio.run(scenario())


def test_stop_completes_quickly_after_a_finished_connection():
    """Regressão: stop() já travou por ~10s (uma corrida entre loop.stop() e o callback que
    resolve o future do run_coroutine_threadsafe) mesmo sem nenhuma conexão ativa no momento
    do stop. Aqui garantimos que parar o motor continua rápido depois de servir uma conexão."""
    async def scenario():
        target_server, target_port = await _start_target_server(b"ola mundo")
        engine, _store = _make_engine("127.0.0.1 +direct\n")
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", HTTP_PORT)
            req = (f"GET http://127.0.0.1:{target_port}/ HTTP/1.1\r\n"
                   f"Host: 127.0.0.1:{target_port}\r\nConnection: close\r\n\r\n").encode()
            writer.write(req)
            await writer.drain()
            await reader.read(-1)
            await asyncio.sleep(0.2)
        finally:
            t0 = time.monotonic()
            engine.stop()
            elapsed = time.monotonic() - t0
            target_server.close()
        assert elapsed < 2.0, f"stop() levou {elapsed:.2f}s (deveria ser quase instantâneo)"
        assert not engine.is_running()

    asyncio.run(scenario())
