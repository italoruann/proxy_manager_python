"""Motor do proxy: sobe os listeners locais (SOCKS5, HTTP e o servidor do PAC), decide o
roteamento de cada conexão usando o motor de regras e faz o encaminhamento (splice) dos bytes."""
from __future__ import annotations

import asyncio
import ipaddress
import threading
import time
from typing import Callable, Optional

from . import httpproxy, process_lookup, socks5
from .config import AppConfig, ProxyProfile
from .logstore import LogEntry, LogStore
from .rules import MatchResult, RuleSet
from .system_integration import build_pac_script, start_pac_server

StatusCallback = Callable[[bool, str], None]


def _literal_ip(host: str) -> Optional[str]:
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        return None


class ProxyEngine:
    def __init__(self, config: AppConfig, log_store: LogStore):
        self.config = config
        self.log_store = log_store
        self.rule_set = RuleSet.parse(config.rules_text)
        self.on_status_change: Optional[StatusCallback] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._servers: list[asyncio.AbstractServer] = []
        self._ready = threading.Event()
        self._active_writers: set[asyncio.StreamWriter] = set()

        self.active_connections = 0
        self.total_bytes_sent = 0
        self.total_bytes_recv = 0
        self.proxy_bytes_sent = 0
        self.proxy_bytes_recv = 0
        self.direct_bytes_sent = 0
        self.direct_bytes_recv = 0

    # -- ciclo de vida -----------------------------------------------------

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def update_config(self, config: AppConfig) -> None:
        self.config = config
        self.rule_set = RuleSet.parse(config.rules_text)

    def start(self) -> None:
        if self.is_running():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="proxy-engine", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass  # o join abaixo ainda serve de rede de segurança
            # Só paramos o loop DEPOIS que _shutdown() terminou de verdade (future.result
            # retornou). Chamar loop.stop() de dentro da própria coroutine rastreada pelo
            # run_coroutine_threadsafe corre o risco de parar o loop antes dele processar o
            # callback que resolve esse future — o que travava stop() por até o timeout inteiro.
            loop.call_soon_threadsafe(loop.stop)
        if thread:
            thread.join(timeout=10)
            if thread.is_alive():
                # o motor não conseguiu parar de fato: não finge que parou, senão a GUI
                # mostraria "parado" com os listeners ainda escutando de verdade.
                return
        self._thread = None
        self._loop = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_servers())
            self._ready.set()
            loop.run_forever()
        except Exception as exc:
            self._ready.set()
            self._emit_status(False, f"Falha ao iniciar o motor: {exc}")
        finally:
            loop.close()

    async def _start_servers(self) -> None:
        settings = self.config.settings
        try:
            socks_server = await asyncio.start_server(self._handle_socks_client, "127.0.0.1", settings.socks_port)
            http_server = await asyncio.start_server(self._handle_http_client, "127.0.0.1", settings.http_port)
            pac_server = await start_pac_server(self._pac_text, settings.pac_port)
        except OSError as exc:
            self._emit_status(False, f"Não foi possível abrir as portas locais: {exc}")
            raise
        self._servers = [socks_server, http_server, pac_server]
        self._emit_status(True, "Motor iniciado")

    def _pac_text(self) -> str:
        return build_pac_script(self.config.settings.socks_port, self.config.settings.http_port)

    async def _shutdown(self) -> None:
        for server in self._servers:
            server.close()

        # "Parar o motor" precisa ser imediato — não esperamos túneis de longa duração (ex.:
        # HTTPS mantido aberto pelo navegador) drenarem sozinhos, senão wait_closed() abaixo
        # ficaria bloqueado indefinidamente e o motor nunca terminaria de parar de verdade.
        for writer in list(self._active_writers):
            try:
                writer.transport.abort()
            except Exception:
                pass
        self._active_writers.clear()

        for server in self._servers:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=3)
            except Exception:
                pass
        self._servers = []
        self._emit_status(False, "Motor parado")
        # loop.stop() é chamado por quem invocou stop(), depois que este future resolver
        # (ver ProxyEngine.stop) — não aqui dentro, para não correr contra o próprio callback
        # de conclusão desta coroutine.

    def _track(self, *writers: asyncio.StreamWriter) -> None:
        self._active_writers.update(writers)

    def _untrack(self, *writers: asyncio.StreamWriter) -> None:
        for writer in writers:
            self._active_writers.discard(writer)

    def _emit_status(self, running: bool, message: str) -> None:
        if self.on_status_change:
            self.on_status_change(running, message)

    # -- decisão de roteamento ----------------------------------------------

    def _resolve_proxy_profile(self, match: MatchResult) -> Optional[ProxyProfile]:
        if match.proxy_name:
            return self.config.find_proxy(match.proxy_name)
        return self.config.default_proxy()

    @staticmethod
    def _rule_label(match: MatchResult) -> str:
        if match.rule:
            return f"{match.rule.pattern} +{match.rule.action}" if match.rule.action != "proxy" else match.rule.pattern
        return "(padrão)"

    async def _prepare(self, target_host: str, target_port: int, peer_ip: str, peer_port: int,
                        listen_port: int, protocol: str) -> tuple[MatchResult, Optional[ProxyProfile], LogEntry]:
        proc = await asyncio.to_thread(process_lookup.lookup_by_local_peer, peer_ip, peer_port, listen_port)
        ip_literal = _literal_ip(target_host)
        match = self.rule_set.match(proc.name, proc.path, target_host, ip_literal,
                                     default_action=self.config.settings.default_action)
        profile: Optional[ProxyProfile] = None
        proxy_label = ""
        if match.action_kind == "proxy":
            profile = self._resolve_proxy_profile(match)
            proxy_label = profile.name if profile else "(nenhum proxy configurado)"

        entry = self.log_store.add(LogEntry(
            pid=proc.pid, process_name=proc.name, process_path=proc.path, protocol=protocol,
            dst_host=target_host, dst_port=target_port, matched_rule=self._rule_label(match),
            action=match.action_kind, proxy_used=proxy_label,
        ))
        return match, profile, entry

    async def _connect_upstream(self, match: MatchResult, profile: Optional[ProxyProfile],
                                 target_host: str, target_port: int):
        if match.action_kind == "direct":
            return await asyncio.open_connection(target_host, target_port)
        if profile is None:
            raise RuntimeError("nenhum perfil de proxy disponível para esta regra")
        if profile.type == "socks5":
            return await socks5.dial_upstream_socks5(profile.host, profile.port, target_host, target_port,
                                                       profile.username, profile.password)
        return await httpproxy.dial_upstream_http_connect(profile.host, profile.port, target_host, target_port,
                                                            profile.username, profile.password)

    # -- SOCKS5 --------------------------------------------------------------

    async def _handle_socks_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        start = time.monotonic()
        peer = writer.get_extra_info("peername") or ("", 0)
        try:
            req = await socks5.server_handshake(reader, writer)
        except Exception:
            writer.close()
            return

        match, profile, entry = await self._prepare(req.host, req.port, peer[0], peer[1],
                                                      self.config.settings.socks_port, "socks5")

        if match.action_kind == "block":
            await socks5.send_server_reply(writer, socks5.REP_NOT_ALLOWED)
            writer.close()
            self.log_store.update(entry.id, status="bloqueada", duration_ms=self._elapsed_ms(start))
            return

        try:
            target_reader, target_writer = await self._connect_upstream(match, profile, req.host, req.port)
        except Exception as exc:
            await socks5.send_server_reply(writer, socks5.REP_HOST_UNREACHABLE)
            writer.close()
            self.log_store.update(entry.id, status="erro", error=str(exc), duration_ms=self._elapsed_ms(start))
            return

        await socks5.send_server_reply(writer, socks5.REP_SUCCESS)
        self.active_connections += 1
        self._track(writer, target_writer)
        try:
            sent, recv = await self._pipe(reader, writer, target_reader, target_writer, match.action_kind)
        finally:
            self.active_connections -= 1
            self._untrack(writer, target_writer)
        self.log_store.update(entry.id, status="concluida", bytes_sent=sent, bytes_recv=recv,
                               duration_ms=self._elapsed_ms(start))

    # -- HTTP / HTTPS (CONNECT) ------------------------------------------------

    async def _handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        start = time.monotonic()
        peer = writer.get_extra_info("peername") or ("", 0)
        try:
            head = await httpproxy.read_request_head(reader)
            target_host, target_port = httpproxy.parse_target(head)
        except Exception:
            writer.close()
            return

        match, profile, entry = await self._prepare(target_host, target_port, peer[0], peer[1],
                                                      self.config.settings.http_port, "http")
        is_connect = head.method == "CONNECT"

        if match.action_kind == "block":
            await self._http_error(writer, 403, "Forbidden")
            self.log_store.update(entry.id, status="bloqueada", duration_ms=self._elapsed_ms(start))
            return

        needs_absolute_form = match.action_kind == "proxy" and profile is not None and profile.type == "http"

        try:
            target_reader, target_writer = await self._connect_upstream(match, profile, target_host, target_port)
            if not is_connect:
                if needs_absolute_form:
                    auth = httpproxy.basic_auth(profile.username, profile.password) if profile.username else None
                    target_writer.write(httpproxy.absolute_form_request(head, auth))
                else:
                    target_writer.write(httpproxy.origin_form_request(head))
                await target_writer.drain()
        except Exception as exc:
            await self._http_error(writer, 502, "Bad Gateway")
            self.log_store.update(entry.id, status="erro", error=str(exc), duration_ms=self._elapsed_ms(start))
            return

        if is_connect:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

        self.active_connections += 1
        self._track(writer, target_writer)
        try:
            sent, recv = await self._pipe(reader, writer, target_reader, target_writer, match.action_kind)
        finally:
            self.active_connections -= 1
            self._untrack(writer, target_writer)
        self.log_store.update(entry.id, status="concluida", bytes_sent=sent, bytes_recv=recv,
                               duration_ms=self._elapsed_ms(start))

    @staticmethod
    async def _http_error(writer: asyncio.StreamWriter, code: int, reason: str) -> None:
        body = f"HTTP/1.1 {code} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        try:
            writer.write(body.encode("ascii"))
            await writer.drain()
        finally:
            writer.close()

    # -- utilidades -----------------------------------------------------------

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    async def _pipe(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter,
                     target_reader: asyncio.StreamReader, target_writer: asyncio.StreamWriter,
                     category: str) -> tuple[int, int]:
        counters = {"sent": 0, "recv": 0}

        async def forward(src: asyncio.StreamReader, dst: asyncio.StreamWriter, key: str) -> None:
            try:
                while True:
                    chunk = await src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
                    n = len(chunk)
                    counters[key] += n
                    if key == "sent":
                        self.total_bytes_sent += n
                        if category == "proxy":
                            self.proxy_bytes_sent += n
                        else:
                            self.direct_bytes_sent += n
                    else:
                        self.total_bytes_recv += n
                        if category == "proxy":
                            self.proxy_bytes_recv += n
                        else:
                            self.direct_bytes_recv += n
            except (ConnectionResetError, BrokenPipeError, OSError, asyncio.IncompleteReadError):
                pass
            finally:
                try:
                    dst.close()
                except Exception:
                    pass

        await asyncio.gather(
            forward(client_reader, target_writer, "sent"),
            forward(target_reader, client_writer, "recv"),
        )
        return counters["sent"], counters["recv"]
