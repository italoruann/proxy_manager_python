"""Testes da tradução de pacotes (NAT "na mão") do modo transparente no Windows. Usa um pacote
falso no lugar de um pacote real do WinDivert — a lógica de tradução (_translate) não depende do
driver de verdade, só da forma do objeto (packet.tcp, packet.is_outbound, packet.dst_addr etc.),
então dá pra testar sem o pacote `pydivert` instalado nem rodar como Administrador."""
from proxy_manager.core.transparent.windows_windivert import WindowsTransparentMode


class _FakeTcp:
    def __init__(self, src_port, syn=False, ack=False, fin=False, rst=False):
        self.src_port = src_port
        self.syn = syn
        self.ack = ack
        self.fin = fin
        self.rst = rst


class _FakePacket:
    def __init__(self, is_outbound, src_addr, dst_addr, dst_port, tcp):
        self.is_outbound = is_outbound
        self.src_addr = src_addr
        self.dst_addr = dst_addr
        self.dst_port = dst_port
        self.tcp = tcp


def test_new_outbound_syn_is_redirected_and_tracked():
    backend = WindowsTransparentMode(transparent_port=58095)
    packet = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                          dst_port=443, tcp=_FakeTcp(src_port=53211, syn=True, ack=False))

    backend._translate(packet)

    assert packet.dst_addr == "127.0.0.1"
    assert packet.dst_port == 58095
    assert backend.resolve_destination(writer=None, peer_port=53211) == ("203.0.113.10", 443)


def test_continuing_outbound_packet_of_tracked_flow_is_also_redirected():
    backend = WindowsTransparentMode(transparent_port=58095)
    syn = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                       dst_port=443, tcp=_FakeTcp(src_port=53211, syn=True))
    backend._translate(syn)

    data_packet = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                               dst_port=443, tcp=_FakeTcp(src_port=53211))
    backend._translate(data_packet)

    assert data_packet.dst_addr == "127.0.0.1"
    assert data_packet.dst_port == 58095


def test_outbound_packet_of_untracked_flow_is_left_alone():
    """Regressão: sem isso, QUALQUER tráfego de saída seria redirecionado, mesmo conexões que
    nunca passaram por um SYN capturado (ex.: o handle começou a capturar no meio de uma conexão
    já estabelecida antes do start())."""
    backend = WindowsTransparentMode(transparent_port=58095)
    packet = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                          dst_port=443, tcp=_FakeTcp(src_port=53211, syn=False, ack=True))

    backend._translate(packet)

    assert packet.dst_addr == "203.0.113.10"
    assert packet.dst_port == 443


def test_inbound_reply_from_local_listener_has_source_restored():
    backend = WindowsTransparentMode(transparent_port=58095)
    syn = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                       dst_port=443, tcp=_FakeTcp(src_port=53211, syn=True))
    backend._translate(syn)

    reply = _FakePacket(is_outbound=False, src_addr="127.0.0.1", dst_addr="192.168.1.50",
                         dst_port=53211, tcp=_FakeTcp(src_port=58095))
    reply.tcp.dst_port = 53211
    backend._translate(reply)

    assert reply.src_addr == "203.0.113.10"
    assert reply.tcp.src_port == 443


def test_flow_is_untracked_after_fin_to_avoid_unbounded_growth():
    backend = WindowsTransparentMode(transparent_port=58095)
    syn = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                       dst_port=443, tcp=_FakeTcp(src_port=53211, syn=True))
    backend._translate(syn)
    assert backend.resolve_destination(writer=None, peer_port=53211) is not None

    fin = _FakePacket(is_outbound=True, src_addr="192.168.1.50", dst_addr="203.0.113.10",
                       dst_port=443, tcp=_FakeTcp(src_port=53211, fin=True))
    backend._translate(fin)

    assert backend.resolve_destination(writer=None, peer_port=53211) is None


def test_resolve_destination_returns_none_for_unknown_port():
    backend = WindowsTransparentMode(transparent_port=58095)
    assert backend.resolve_destination(writer=None, peer_port=9999) is None


def test_start_reports_missing_pydivert_dependency(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pydivert":
            raise ImportError("no module named pydivert")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = WindowsTransparentMode(transparent_port=58095)

    ok, message = backend.start()

    assert ok is False
    assert "pydivert" in message.lower()
