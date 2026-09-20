"""Testes de apply_settings_live: trocar porta/modo transparente com o motor rodando, SEM
parar ele. O ponto central é provar que uma conexão já aberta continua funcionando normalmente
quando uma porta *não relacionada* muda — diferente de stop()+start(), que derrubaria tudo."""
import asyncio
import socket
from dataclasses import replace

from proxy_manager.core.config import AppConfig, Settings
from proxy_manager.core.engine import ProxyEngine
from proxy_manager.core.logstore import LogStore
from proxy_manager.core.socks5 import dial_upstream_socks5

SOCKS_PORT = 58900
HTTP_PORT = 58901
PAC_PORT = 58902


def _make_engine(rules_text: str = "127.0.0.1 +direct\n") -> tuple[ProxyEngine, LogStore]:
    settings = Settings(socks_port=SOCKS_PORT, http_port=HTTP_PORT, pac_port=PAC_PORT,
                         default_action="block")
    cfg = AppConfig(proxies=[], rules_text=rules_text, settings=settings)
    store = LogStore(retention_days=1)
    return ProxyEngine(cfg, store), store


async def _start_echo_server():
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _fetch_pac(port: int) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /proxy.pac HTTP/1.1\r\n\r\n")
    await writer.drain()
    data = await reader.read(-1)
    writer.close()
    return data


def test_live_port_change_does_not_disturb_an_already_open_connection():
    async def scenario():
        target_server, target_port = await _start_echo_server()
        engine, _store = _make_engine()
        engine.start()
        try:
            reader, writer = await dial_upstream_socks5("127.0.0.1", SOCKS_PORT, "127.0.0.1", target_port)
            writer.write(b"ping1")
            await writer.drain()
            assert await reader.read(5) == b"ping1"

            # troca a porta do PAC (não tem nada a ver com essa conexão SOCKS5 já aberta)
            new_settings = replace(engine.config.settings, pac_port=PAC_PORT + 1)
            new_config = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=new_settings)
            ok, message = engine.apply_settings_live(new_config)
            assert ok is True, message

            # a conexão que já estava aberta ANTES da troca continua funcionando normalmente
            writer.write(b"ping2")
            await writer.drain()
            assert await reader.read(5) == b"ping2"
        finally:
            engine.stop()
            target_server.close()

    asyncio.run(scenario())


def test_live_pac_port_change_moves_the_listener():
    async def scenario():
        engine, _store = _make_engine()
        engine.start()
        try:
            assert b"200" in await _fetch_pac(PAC_PORT)

            new_settings = replace(engine.config.settings, pac_port=PAC_PORT + 2)
            new_config = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=new_settings)
            ok, message = engine.apply_settings_live(new_config)
            assert ok is True, message
            assert engine.config.settings.pac_port == PAC_PORT + 2

            assert b"200" in await _fetch_pac(PAC_PORT + 2)
            try:
                await asyncio.wait_for(asyncio.open_connection("127.0.0.1", PAC_PORT), timeout=1)
                assert False, "a porta antiga do PAC deveria ter parado de aceitar conexões"
            except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                pass
        finally:
            engine.stop()

    asyncio.run(scenario())


def test_apply_settings_live_returns_error_when_engine_not_running():
    engine, _store = _make_engine()
    new_config = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=engine.config.settings)

    ok, message = engine.apply_settings_live(new_config)

    assert ok is False
    assert "não está em execução" in message


def test_apply_settings_live_reverts_port_on_bind_failure():
    async def scenario():
        engine, _store = _make_engine()
        engine.start()
        occupied_port = 58909
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", occupied_port))
        blocker.listen(1)
        try:
            new_settings = replace(engine.config.settings, socks_port=occupied_port)
            new_config = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=new_settings)

            ok, message = engine.apply_settings_live(new_config)

            assert ok is False
            assert str(occupied_port) in message
            # a config reflete a porta REAL que continua escutando, não a que falhou
            assert engine.config.settings.socks_port == SOCKS_PORT

            # e a porta antiga continua aceitando conexões normalmente (só confirma que o
            # listener segue de pé; não precisa completar um CONNECT de verdade pra isso)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", SOCKS_PORT), timeout=2)
            writer.close()
        finally:
            blocker.close()
            engine.stop()

    asyncio.run(scenario())


def test_apply_settings_live_toggles_transparent_mode(monkeypatch):
    from proxy_manager.core import engine as engine_module

    class _FakeBackend:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True
            return True, "ok (fake)"

        def stop(self):
            self.stopped = True
            return True, "ok (fake)"

        def resolve_destination(self, writer, peer_port):
            return None

    async def scenario():
        fake_backend = _FakeBackend()
        monkeypatch.setattr(engine_module, "_create_transparent_backend", lambda port: fake_backend)

        engine, _store = _make_engine()
        engine.start()
        try:
            assert engine.transparent_backend is None

            new_settings = replace(engine.config.settings, transparent_mode_enabled=True,
                                    transparent_port=58908)
            new_config = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=new_settings)
            ok, message = engine.apply_settings_live(new_config)

            assert ok is True, message
            assert fake_backend.started is True
            assert engine.transparent_backend is fake_backend

            new_settings2 = replace(engine.config.settings, transparent_mode_enabled=False)
            new_config2 = AppConfig(proxies=[], rules_text=engine.config.rules_text, settings=new_settings2)
            ok2, message2 = engine.apply_settings_live(new_config2)

            assert ok2 is True, message2
            assert fake_backend.stopped is True
            assert engine.transparent_backend is None
        finally:
            engine.stop()

    asyncio.run(scenario())
