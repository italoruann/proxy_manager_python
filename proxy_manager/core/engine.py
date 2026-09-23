"""Motor do proxy: sobe os listeners locais (SOCKS5, HTTP e o servidor do PAC), decide o
roteamento de cada conexão usando o motor de regras e faz o encaminhamento (splice) dos bytes."""
from __future__ import annotations

import asyncio
import ipaddress
import platform
import threading
import time
from typing import Callable, Optional, Protocol

from . import httpproxy, ip_check, process_lookup, socks5
from .config import AppConfig, ProxyProfile
from .logstore import LogEntry, LogStore
from .rules import MatchResult, RuleSet
from .system_integration import build_pac_script, start_pac_server
from .transparent import sniff

StatusCallback = Callable[[bool, str], None]
# profile_id, ip anterior ("" se essa é a primeira verificação), ip atual
EgressIpCallback = Callable[[str, str, str], None]

# Quanto tempo um IP de saída verificado (via ip-api.com) fica valendo em cache antes de
# verificar de novo — evita bater no ip-api.com a cada conexão (o free tier tem limite de
# requisições por minuto) já que o IP de saída de um proxy raramente muda de um minuto pro outro.
EGRESS_IP_CACHE_TTL = 600.0


class TransparentBackend(Protocol):
    """Interface comum a LinuxTransparentMode e WindowsTransparentMode — o engine não precisa
    saber qual das duas está ativa."""

    def start(self) -> tuple[bool, str]: ...
    def stop(self) -> tuple[bool, str]: ...
    def resolve_destination(self, writer: asyncio.StreamWriter, peer_port: int) -> Optional[tuple[str, int]]: ...


def _create_transparent_backend(transparent_port: int) -> Optional[TransparentBackend]:
    system = platform.system()
    if system == "Linux":
        from .transparent.linux_nftables import LinuxTransparentMode
        return LinuxTransparentMode(transparent_port)
    if system == "Windows":
        from .transparent.windows_windivert import WindowsTransparentMode
        return WindowsTransparentMode(transparent_port)
    return None


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
        self.on_egress_ip_change: Optional[EgressIpCallback] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        # Listeners guardados por nome (em vez de uma lista solta) para permitir trocar só o
        # que realmente mudou (ver apply_settings_live) sem precisar derrubar o motor inteiro.
        self._socks_server: Optional[asyncio.AbstractServer] = None
        self._http_server: Optional[asyncio.AbstractServer] = None
        self._pac_server: Optional[asyncio.AbstractServer] = None
        self._transparent_server: Optional[asyncio.AbstractServer] = None
        self._ready = threading.Event()
        self._active_writers: set[asyncio.StreamWriter] = set()
        self.transparent_backend: Optional[TransparentBackend] = None
        # Cache do IP de saída verificado por perfil de proxy: chave inclui host/porta/tipo (não
        # só o id) pra invalidar sozinho se o usuário editar o perfil, em vez de esperar o TTL
        # expirar mostrando um IP que já não é mais o de verdade.
        self._egress_ip_cache: dict[str, tuple[float, str]] = {}
        self._egress_ip_checking: set[str] = set()
        # Último IP de saída conhecido POR PERFIL (chave = profile.id, sem host/porta/tipo) —
        # ao contrário de _egress_ip_cache, essa chave não muda se o usuário editar host/porta,
        # então uma reverificação forçada por essa edição ainda é comparada contra o IP anterior
        # de verdade, permitindo avisar a GUI "mudou de X para Y" em vez de só mostrar Y.
        self._egress_ip_by_profile: dict[str, str] = {}
        # Tarefas de segundo plano por conexão (resolução de dst_ip, verificação de proxy_ip):
        # rastreadas pra poderem ser canceladas em _shutdown() — sem isso, uma verificação de
        # egress IP em andamento (uma chamada de rede de verdade ao ip-api.com) sobreviveria ao
        # próprio motor já "parado", vazando o socket até o GC derrubar a tarefa sozinho.
        self._background_tasks: set[asyncio.Task] = set()

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
            self._socks_server = await asyncio.start_server(
                self._handle_socks_client, "127.0.0.1", settings.socks_port)
            self._http_server = await asyncio.start_server(
                self._handle_http_client, "127.0.0.1", settings.http_port)
            self._pac_server = await start_pac_server(self._pac_text, settings.pac_port)
        except OSError as exc:
            self._emit_status(False, f"Não foi possível abrir as portas locais: {exc}")
            raise

        if settings.transparent_mode_enabled:
            backend = _create_transparent_backend(settings.transparent_port)
            if backend is None:
                self._emit_status(False, "Modo transparente não é suportado nesta plataforma.")
                raise RuntimeError("modo transparente não suportado nesta plataforma")
            ok, message = backend.start()
            if not ok:
                self._emit_status(False, f"Falha ao ativar o modo transparente: {message}")
                raise RuntimeError(message)
            self._transparent_server = await asyncio.start_server(
                self._handle_transparent_client, "127.0.0.1", settings.transparent_port)
            self.transparent_backend = backend

        self._emit_status(True, "Motor iniciado")

    def _pac_text(self) -> str:
        return build_pac_script(self.config.settings.socks_port, self.config.settings.http_port)

    def _all_servers(self) -> list[asyncio.AbstractServer]:
        return [s for s in (self._socks_server, self._http_server, self._pac_server,
                             self._transparent_server) if s is not None]

    async def _shutdown(self) -> None:
        servers = self._all_servers()
        for server in servers:
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

        # Mesma lógica pras tarefas de segundo plano (resolução de dst_ip / verificação de
        # proxy_ip via ip-api.com): cancela e espera elas de fato pararem, em vez de deixá-las
        # penduradas segurando um socket depois do motor já ter "parado".
        pending_tasks = list(self._background_tasks)
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        for server in servers:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=3)
            except Exception:
                pass
        self._socks_server = None
        self._http_server = None
        self._pac_server = None
        self._transparent_server = None

        if self.transparent_backend is not None:
            await asyncio.to_thread(self.transparent_backend.stop)
            self.transparent_backend = None

        self._emit_status(False, "Motor parado")
        # loop.stop() é chamado por quem invocou stop(), depois que este future resolver
        # (ver ProxyEngine.stop) — não aqui dentro, para não correr contra o próprio callback
        # de conclusão desta coroutine.

    # -- aplicar configuração sem parar o motor ------------------------------

    def apply_settings_live(self, new_config: AppConfig) -> tuple[bool, str]:
        """Troca portas/modo transparente SEM parar o motor: fecha e reabre só o listener cuja
        porta realmente mudou, deixando os demais listeners e TODAS as conexões já em andamento
        (self._active_writers) completamente intactos — diferente de stop()+start(), que derruba
        tudo. A única descontinuidade inevitável é a porta específica que muda: não dá pra mover
        um socket escutando pra outra porta sem fechar e abrir de novo, mas as conexões que já
        estavam estabelecidas nela continuam rodando normalmente (elas usam um socket separado do
        socket que só *aceita novas* conexões).

        Só funciona com o motor rodando; chame update_config() + start() normalmente quando ele
        estiver parado."""
        loop = self._loop
        if not self.is_running() or loop is None or not loop.is_running():
            return False, "O motor não está em execução."
        future = asyncio.run_coroutine_threadsafe(self._apply_settings_live(new_config), loop)
        try:
            return future.result(timeout=10)
        except Exception as exc:
            return False, f"Falha ao aplicar configurações: {exc}"

    async def _apply_settings_live(self, new_config: AppConfig) -> tuple[bool, str]:
        old_settings = self.config.settings
        new_settings = new_config.settings
        applied: list[str] = []
        errors: list[str] = []

        if new_settings.socks_port != old_settings.socks_port:
            try:
                self._socks_server = await self._replace_server(
                    self._socks_server, self._handle_socks_client, new_settings.socks_port)
                applied.append(f"SOCKS5 → porta {new_settings.socks_port}")
            except OSError as exc:
                errors.append(f"porta SOCKS5 ({new_settings.socks_port}): {exc}")
                new_settings.socks_port = old_settings.socks_port

        if new_settings.http_port != old_settings.http_port:
            try:
                self._http_server = await self._replace_server(
                    self._http_server, self._handle_http_client, new_settings.http_port)
                applied.append(f"HTTP → porta {new_settings.http_port}")
            except OSError as exc:
                errors.append(f"porta HTTP ({new_settings.http_port}): {exc}")
                new_settings.http_port = old_settings.http_port

        if new_settings.pac_port != old_settings.pac_port:
            try:
                self._pac_server = await self._replace_pac_server(self._pac_server, new_settings.pac_port)
                applied.append(f"PAC → porta {new_settings.pac_port}")
            except OSError as exc:
                errors.append(f"porta do PAC ({new_settings.pac_port}): {exc}")
                new_settings.pac_port = old_settings.pac_port

        transparent_changed = (
            new_settings.transparent_mode_enabled != old_settings.transparent_mode_enabled
            or (new_settings.transparent_mode_enabled
                and new_settings.transparent_port != old_settings.transparent_port)
        )
        if transparent_changed:
            try:
                await self._apply_transparent_settings(new_settings)
                applied.append("modo transparente")
            except (OSError, RuntimeError) as exc:
                errors.append(f"modo transparente: {exc}")
                new_settings.transparent_mode_enabled = old_settings.transparent_mode_enabled
                new_settings.transparent_port = old_settings.transparent_port

        # Só commitamos a config nova (e re-emitimos status, que é o que faz o AppContext
        # reaplicar a URL do PAC no SO se a porta dele mudou) depois de já termos revertido, nos
        # próprios new_settings, qualquer item que tenha falhado — assim self.config sempre
        # reflete exatamente o que está de fato escutando em cada porta neste momento.
        self.config = new_config
        self.rule_set = RuleSet.parse(new_config.rules_text)

        if applied:
            self._emit_status(True, "Configurações aplicadas sem parar o motor: " + ", ".join(applied) + ".")

        if errors:
            return False, ("Alguns itens não puderam ser aplicados (mantidos como estavam): "
                            + "; ".join(errors))
        if not applied:
            return True, "Nada mudou nas portas/modo transparente."
        return True, "Aplicado sem parar o motor: " + ", ".join(applied) + "."

    @staticmethod
    async def _replace_server(old_server: Optional[asyncio.AbstractServer], handler, new_port: int,
                               ) -> asyncio.AbstractServer:
        # Abre o novo listener ANTES de fechar o velho: se a porta nova estiver ocupada (ou
        # qualquer outro OSError), o velho continua no ar e ninguém percebe a falha como uma
        # interrupção — só como "não consegui trocar pra essa porta".
        new_server = await asyncio.start_server(handler, "127.0.0.1", new_port)
        if old_server is not None:
            old_server.close()
            await asyncio.wait_for(old_server.wait_closed(), timeout=3)
        return new_server

    async def _replace_pac_server(self, old_server: Optional[asyncio.AbstractServer], new_port: int,
                                   ) -> asyncio.AbstractServer:
        new_server = await start_pac_server(self._pac_text, new_port)
        if old_server is not None:
            old_server.close()
            await asyncio.wait_for(old_server.wait_closed(), timeout=3)
        return new_server

    async def _apply_transparent_settings(self, new_settings) -> None:
        old_backend = self.transparent_backend
        old_server = self._transparent_server

        if not new_settings.transparent_mode_enabled:
            if old_server is not None:
                old_server.close()
                await asyncio.wait_for(old_server.wait_closed(), timeout=3)
                self._transparent_server = None
            if old_backend is not None:
                await asyncio.to_thread(old_backend.stop)
                self.transparent_backend = None
            return

        backend = _create_transparent_backend(new_settings.transparent_port)
        if backend is None:
            raise RuntimeError("modo transparente não é suportado nesta plataforma")
        ok, message = await asyncio.to_thread(backend.start)
        if not ok:
            raise RuntimeError(message)

        new_server = await asyncio.start_server(
            self._handle_transparent_client, "127.0.0.1", new_settings.transparent_port)

        # Mesma ideia do _replace_server: só desliga o backend/listener antigos depois que os
        # novos já estão de pé, então uma falha não deixa o modo transparente sem nada rodando.
        if old_server is not None:
            old_server.close()
            await asyncio.wait_for(old_server.wait_closed(), timeout=3)
        if old_backend is not None:
            await asyncio.to_thread(old_backend.stop)

        self._transparent_server = new_server
        self.transparent_backend = backend

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
                        listen_port: int, protocol: str, match_host: Optional[str] = None,
                        original_dst: Optional[tuple[str, int]] = None,
                        ) -> tuple[MatchResult, Optional[ProxyProfile], LogEntry]:
        """`match_host` só é usado pelo modo transparente: lá, `target_host` é sempre o IP real
        (recuperado via SO_ORIGINAL_DST/NAT, precisa continuar valendo pras regras por IP/CIDR),
        enquanto `match_host` é o domínio, quando dá pra descobrir espiando SNI/Host — usado nas
        regras por domínio e no log, no lugar do IP cru. `original_dst` (também só do modo
        transparente) é o destino que o app discou — necessário pra achar o processo dono da
        conexão, ver process_lookup.lookup_by_local_peer."""
        proc = await asyncio.to_thread(process_lookup.lookup_by_local_peer, peer_ip, peer_port,
                                       listen_port, original_dst)
        ip_literal = _literal_ip(target_host)
        host_for_rules = match_host or target_host
        match = self.rule_set.match(proc.name, proc.path, host_for_rules, ip_literal,
                                     default_action=self.config.settings.default_action)
        profile: Optional[ProxyProfile] = None
        proxy_label = ""
        proxy_ip_value = ""
        needs_egress_check = False
        if match.action_kind == "proxy":
            profile = self._resolve_proxy_profile(match)
            proxy_label = profile.name if profile else "(nenhum proxy configurado)"
            if profile:
                cached = self._egress_ip_cache.get(self._egress_cache_key(profile))
                if cached:
                    proxy_ip_value = cached[1]
                    needs_egress_check = (time.time() - cached[0]) >= EGRESS_IP_CACHE_TTL
                else:
                    needs_egress_check = True

        entry = self.log_store.add(LogEntry(
            pid=proc.pid, process_name=proc.name, process_path=proc.path, protocol=protocol,
            dst_host=host_for_rules, dst_ip=ip_literal or "", dst_port=target_port,
            matched_rule=self._rule_label(match), action=match.action_kind, proxy_used=proxy_label,
            proxy_ip=proxy_ip_value,
        ))
        if ip_literal is None:
            # target_host é um domínio (não um IP literal): resolve em segundo plano só pra
            # exibir no log, sem atrasar a conexão nem o roteamento.
            self._spawn_background(self._resolve_dst_ip(entry.id, target_host))
        if profile is not None and needs_egress_check:
            # Verifica (ou reverifica, se o cache expirou) o IP de saída real do proxy, consultando
            # o ip-api.com através do próprio túnel — é o único jeito confiável de saber o IP que um
            # site remoto de fato vê; o endereço de conexão do perfil pode divergir dele (proxies com
            # pool de IPs). Em segundo plano: não atrasa a conexão que disparou a verificação.
            self._spawn_background(
                self._refresh_egress_ip(profile, entry.id, had_fallback=bool(proxy_ip_value)))
        return match, profile, entry

    def _spawn_background(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def seed_egress_ip_state(self, current_ip_by_profile: dict[str, str]) -> None:
        """Restaura o último IP de saída conhecido por perfil (de uma sessão anterior), chamado
        logo após a criação do motor. Sem isso, a primeira verificação depois de reabrir o app
        trataria tudo como 'primeira detecção' (sem IP anterior pra comparar) e o histórico
        antes/depois persistido nunca receberia uma nova transição de verdade."""
        self._egress_ip_by_profile.update(current_ip_by_profile)

    @staticmethod
    def _egress_cache_key(profile: ProxyProfile) -> str:
        # Inclui host/porta/tipo (não só o id) pra invalidar sozinho se o usuário editar o
        # perfil, em vez de continuar mostrando um IP que já não é mais o de verdade até o TTL
        # expirar.
        return f"{profile.id}:{profile.type}:{profile.host}:{profile.port}"

    async def _resolve_dst_ip(self, entry_id: str, host: str) -> None:
        try:
            loop = asyncio.get_running_loop()
            infos = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=2.0)
        except Exception:
            return
        if infos:
            self.log_store.update(entry_id, dst_ip=infos[0][4][0])

    async def _refresh_egress_ip(self, profile: ProxyProfile, entry_id: str, had_fallback: bool) -> None:
        key = self._egress_cache_key(profile)
        if key in self._egress_ip_checking:
            return
        self._egress_ip_checking.add(key)
        try:
            ip = await ip_check.fetch_egress_ip(profile)
        finally:
            self._egress_ip_checking.discard(key)
        if ip:
            self._egress_ip_cache[key] = (time.time(), ip)
            self.log_store.update(entry_id, proxy_ip=ip)
            previous_ip = self._egress_ip_by_profile.get(profile.id, "")
            if ip != previous_ip:
                self._egress_ip_by_profile[profile.id] = ip
                self._emit_egress_ip_change(profile.id, previous_ip, ip)
        elif not had_fallback:
            # "?" sinaliza "verificação falhou" pra GUI (proxy inatingível a partir do ip-api.com,
            # timeout etc.) em vez de deixar a célula presa em "verificando…" pra sempre. Se já
            # havia um valor em cache (mesmo expirado) pra mostrar, mantém ele em vez de apagar
            # uma informação boa por causa de uma reverificação que falhou.
            self.log_store.update(entry_id, proxy_ip="?")

    def _emit_egress_ip_change(self, profile_id: str, previous_ip: str, current_ip: str) -> None:
        if self.on_egress_ip_change:
            self.on_egress_ip_change(profile_id, previous_ip, current_ip)

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

    # -- Transparente (nftables no Linux / WinDivert no Windows) ------

    async def _handle_transparent_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        start = time.monotonic()
        peer = writer.get_extra_info("peername") or ("", 0)
        backend = self.transparent_backend
        destination = backend.resolve_destination(writer, peer[1]) if backend else None
        if destination is None:
            # Não há como saber pra onde essa conexão deveria ir de verdade (backend desligado,
            # ou alguém conectou direto nessa porta por fora do redirect) — não dá pra encaminhar.
            writer.close()
            return
        target_host, target_port = destination

        # Sem CONNECT nem Host explícito aqui — espiamos os primeiros bytes que o cliente manda
        # (SNI do TLS em 443, ou o header Host em 80) só pra permitir regras por domínio; os
        # mesmos bytes são sempre repassados ao destino de verdade logo abaixo, intactos.
        prefix = b""
        if target_port in (80, 443):
            try:
                prefix = await asyncio.wait_for(reader.read(4096), timeout=0.3)
            except (asyncio.TimeoutError, OSError):
                prefix = b""

        sniffed_host = None
        if prefix:
            if target_port == 443:
                sniffed_host = sniff.extract_sni(prefix)
            elif target_port == 80:
                sniffed_host = sniff.extract_http_host(prefix)

        match, profile, entry = await self._prepare(target_host, target_port, peer[0], peer[1],
                                                      self.config.settings.transparent_port,
                                                      "transparente", match_host=sniffed_host,
                                                      original_dst=destination)

        if match.action_kind == "block":
            writer.close()
            self.log_store.update(entry.id, status="bloqueada", duration_ms=self._elapsed_ms(start))
            return

        try:
            # Sempre discamos o IP original de verdade (nunca o hostname espiado): é exatamente
            # o destino que o próprio aplicativo escolheu, sem risco de uma nova resolução DNS
            # bater num servidor diferente (round-robin/CDN geolocalizado).
            target_reader, target_writer = await self._connect_upstream(match, profile, target_host, target_port)
            if prefix:
                target_writer.write(prefix)
                await target_writer.drain()
        except Exception as exc:
            writer.close()
            self.log_store.update(entry.id, status="erro", error=str(exc), duration_ms=self._elapsed_ms(start))
            return

        if prefix:
            n = len(prefix)
            self.total_bytes_sent += n
            if match.action_kind == "proxy":
                self.proxy_bytes_sent += n
            else:
                self.direct_bytes_sent += n

        self.active_connections += 1
        self._track(writer, target_writer)
        try:
            sent, recv = await self._pipe(reader, writer, target_reader, target_writer, match.action_kind)
        finally:
            self.active_connections -= 1
            self._untrack(writer, target_writer)
        self.log_store.update(entry.id, status="concluida", bytes_sent=sent + len(prefix), bytes_recv=recv,
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
