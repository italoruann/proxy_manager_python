"""Modo transparente no Windows: usa o driver assinado WinDivert (via bindings `pydivert`) pra
interceptar pacotes IP em nível de rede e fazer uma NAT "na mão" pro listener transparente do
ProxyEngine — a mesma ideia do REDIRECT do iptables no Linux, só que sem suporte nativo do SO
pra isso, então mantemos nós mesmos a tabela de tradução (destino original por porta de origem
do processo que abriu a conexão).

Como funciona, pacote a pacote:
1. Um SYN de saída, não destinado à nossa porta transparente e fora do loopback, é uma conexão
   nova: guardamos (porta de origem -> destino original) na tabela e reescrevemos o destino do
   pacote pra 127.0.0.1:<porta transparente>.
2. Todo pacote de saída SEGUINTE dessa mesma conexão (não só o SYN) também precisa ser
   reescrito: o socket do app que abriu a conexão não sabe que os pacotes foram desviados, então
   o Windows continua endereçando os pacotes dele pro destino original até nós interceptarmos de
   novo.
3. Pacotes de volta que saem do NOSSO listener local (origem 127.0.0.1:<porta transparente>) têm
   o endereço de origem reescrito de volta pro destino original antes de seguir — senão a pilha
   TCP/IP do processo que abriu a conexão rejeitaria a resposta por não bater com o destino que
   ele mesmo discou.

Cobre só IPv4/TCP. Exige rodar como Administrador (o driver WinDivert não abre sem isso) e o
pacote `pydivert` instalado — nenhum dos dois é verificado até start() ser chamado."""
from __future__ import annotations

import platform
import threading
from typing import Optional


def is_supported() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import pydivert  # noqa: F401
    except ImportError:
        return False
    return True


class WindowsTransparentMode:
    def __init__(self, transparent_port: int):
        self.transparent_port = transparent_port
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._handle = None
        self._lock = threading.Lock()
        # porta de origem (no host local) -> (ip, porta) do destino original antes do redirect
        self._nat_table: dict[int, tuple[str, int]] = {}

    def start(self) -> tuple[bool, str]:
        try:
            import pydivert
        except ImportError:
            return False, "Pacote 'pydivert' não instalado. Rode: pip install pydivert"

        filter_expr = (
            f"tcp and ("
            f"(outbound and !loopback and tcp.DstPort != {self.transparent_port}) or "
            f"(loopback and tcp.SrcPort == {self.transparent_port})"
            f")"
        )
        try:
            handle = pydivert.WinDivert(filter_expr)
            handle.open()
        except OSError as exc:
            return False, (f"Falha ao abrir o driver WinDivert: {exc}. Confirme que está rodando "
                            "como Administrador e que o pacote pydivert está instalado corretamente.")

        self._handle = handle
        self._stop_event.clear()
        with self._lock:
            self._nat_table.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True,
                                         name="windivert-transparent")
        self._thread.start()
        return True, f"Modo transparente ativo — redirecionando TCP para 127.0.0.1:{self.transparent_port}."

    def stop(self) -> tuple[bool, str]:
        self._stop_event.set()
        if self._handle is not None:
            try:
                self._handle.close()  # desbloqueia o recv() pendente na thread de captura
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._handle = None
        with self._lock:
            self._nat_table.clear()
        return True, "Modo transparente desligado."

    def resolve_destination(self, writer, peer_port: int) -> Optional[tuple[str, int]]:
        """Interface comum com LinuxTransparentMode (que usa `writer`; aqui é ignorado porque
        no Windows guardamos nós mesmos a tradução, indexada pela porta de origem do processo
        que abriu a conexão — preservada pelo redirect)."""
        with self._lock:
            return self._nat_table.get(peer_port)

    def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                packet = self._handle.recv()
            except OSError:
                break  # handle fechado por stop()

            self._translate(packet)

            try:
                self._handle.send(packet)
            except OSError:
                break

    def _translate(self, packet) -> None:
        tcp = packet.tcp
        if tcp is None:
            return

        if packet.is_outbound:
            with self._lock:
                tracked = self._nat_table.get(tcp.src_port)
            is_new_syn = tcp.syn and not tcp.ack
            if tracked is None and is_new_syn:
                tracked = (packet.dst_addr, packet.dst_port)
                with self._lock:
                    self._nat_table[tcp.src_port] = tracked
            if tracked is not None:
                packet.dst_addr = "127.0.0.1"
                packet.dst_port = self.transparent_port
                if tcp.fin or tcp.rst:
                    with self._lock:
                        self._nat_table.pop(tcp.src_port, None)
        else:
            # Resposta vinda do nosso próprio listener local (127.0.0.1:transparent_port),
            # endereçada de volta ao processo que originou a conexão redirecionada.
            if packet.src_addr == "127.0.0.1" and tcp.src_port == self.transparent_port:
                with self._lock:
                    original = self._nat_table.get(tcp.dst_port)
                if original is not None:
                    packet.src_addr, tcp.src_port = original
