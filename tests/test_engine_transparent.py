"""Testes de integração do modo transparente: sobe o engine de verdade com um backend de
transparência FALSO (nunca mexe em iptables/WinDivert de verdade, então roda em qualquer SO/CI
sem privilégio nenhum) pra validar a wiring inteira — ciclo de vida do backend junto com o
motor, listener transparente, sniff de SNI/Host pra regras por domínio, e o pipe até o destino
real usando o IP original."""
import asyncio

from proxy_manager.core import engine as engine_module
from proxy_manager.core.config import AppConfig, Settings
from proxy_manager.core.engine import ProxyEngine
from proxy_manager.core.logstore import LogStore
from tests.test_engine import _start_target_server
from tests.test_transparent_sniff import _build_client_hello

TRANSPARENT_PORT = 58795


class _FakeTransparentBackend:
    def __init__(self, fixed_destination):
        self.fixed_destination = fixed_destination
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return True, "ok (fake)"

    def stop(self):
        self.stopped = True
        return True, "ok (fake)"

    def resolve_destination(self, writer, peer_port):
        return self.fixed_destination


def _make_transparent_engine(rules_text: str, fake_backend, default_action="block"):
    settings = Settings(socks_port=58780, http_port=58781, pac_port=58790,
                         transparent_mode_enabled=True, transparent_port=TRANSPARENT_PORT,
                         default_action=default_action)
    cfg = AppConfig(proxies=[], rules_text=rules_text, settings=settings)
    store = LogStore(retention_days=1)
    return ProxyEngine(cfg, store), store


def test_transparent_backend_lifecycle_follows_engine(monkeypatch):
    """O backend (iptables/WinDivert) precisa ligar ANTES do motor aceitar dizer que está no ar,
    e desligar como parte do stop() — nunca deixar o redirect de sistema ativo com o motor
    parado (senão qualquer app transparente ficaria sem rede nenhuma)."""
    async def scenario():
        fake_backend = _FakeTransparentBackend(fixed_destination=("127.0.0.1", 1))
        monkeypatch.setattr(engine_module, "_create_transparent_backend", lambda port: fake_backend)

        engine, _store = _make_transparent_engine("* +direct\n", fake_backend)
        engine.start()
        assert fake_backend.started
        assert engine.transparent_backend is fake_backend

        engine.stop()
        assert fake_backend.stopped
        assert engine.transparent_backend is None

    asyncio.run(scenario())


def test_transparent_direct_relay_uses_resolved_destination(monkeypatch):
    async def scenario():
        target_server, target_port = await _start_target_server(b"via transparente")
        fake_backend = _FakeTransparentBackend(fixed_destination=("127.0.0.1", target_port))
        monkeypatch.setattr(engine_module, "_create_transparent_backend", lambda port: fake_backend)

        engine, store = _make_transparent_engine("127.0.0.1 +direct\n", fake_backend)
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", TRANSPARENT_PORT)
            writer.write(b"GET / HTTP/1.0\r\n\r\n")  # porta do alvo nao eh 80/443: sem sniff
            await writer.drain()
            data = await reader.read(-1)
            assert b"via transparente" in data

            await asyncio.sleep(0.2)
            entries = [e for e in store.recent() if e.protocol == "transparente"]
            assert any(e.action == "direct" and e.status == "concluida" for e in entries)
        finally:
            engine.stop()
            target_server.close()

    asyncio.run(scenario())


def test_transparent_sni_sniffing_enables_domain_rule(monkeypatch):
    """Sem CONNECT nem Host explícito no modo transparente, só dá pra casar `*.paypal.com` se a
    gente espiar o SNI do ClientHello TLS — usa +block pra não precisar de um servidor de
    verdade escutando na porta 443 (privilegiada em Linux, indisponível em CI sem root)."""
    async def scenario():
        fake_backend = _FakeTransparentBackend(fixed_destination=("203.0.113.10", 443))
        monkeypatch.setattr(engine_module, "_create_transparent_backend", lambda port: fake_backend)

        engine, store = _make_transparent_engine("*.paypal.com +block\n", fake_backend,
                                                    default_action="direct")
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", TRANSPARENT_PORT)
            writer.write(_build_client_hello("checkout.paypal.com"))
            await writer.drain()
            await asyncio.sleep(0.3)

            entries = [e for e in store.recent() if e.dst_host == "checkout.paypal.com"]
            assert entries, "deveria ter descoberto e logado o host via SNI"
            assert entries[-1].action == "block"
            assert entries[-1].matched_rule == "*.paypal.com +block"
        finally:
            engine.stop()

    asyncio.run(scenario())


def test_transparent_http_host_sniffing_enables_domain_rule(monkeypatch):
    """Mesma ideia da regra por SNI, mas pra HTTP em texto puro (porta 80): o hostname vem do
    cabeçalho Host, não de um handshake TLS."""
    async def scenario():
        fake_backend = _FakeTransparentBackend(fixed_destination=("203.0.113.10", 80))
        monkeypatch.setattr(engine_module, "_create_transparent_backend", lambda port: fake_backend)

        engine, store = _make_transparent_engine("*.exemplo.com +block\n", fake_backend,
                                                    default_action="direct")
        engine.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", TRANSPARENT_PORT)
            writer.write(b"GET /caminho HTTP/1.1\r\nHost: www.exemplo.com\r\nConnection: close\r\n\r\n")
            await writer.drain()
            await asyncio.sleep(0.3)

            entries = [e for e in store.recent() if e.dst_host == "www.exemplo.com"]
            assert entries, "deveria ter descoberto e logado o host via cabeçalho Host"
            assert entries[-1].action == "block"
            assert entries[-1].matched_rule == "*.exemplo.com +block"
        finally:
            engine.stop()

    asyncio.run(scenario())
