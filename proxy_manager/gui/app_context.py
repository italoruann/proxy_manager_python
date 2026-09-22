"""Estado compartilhado da aplicação: config, log store e o motor, expostos à GUI via sinais Qt
thread-safe (o motor roda em outra thread; os callbacks viram Signal.emit aqui)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import system_integration
from ..core.config import AppConfig, load_config, save_config
from ..core.egress_ip_store import load_egress_ip_state, save_egress_ip_state
from ..core.engine import ProxyEngine
from ..core.logstore import LogEntry, LogStore
from .log_model import LogTableModel

# Sob carga (uma página com muitas conexões simultâneas), o motor pode gerar dezenas de eventos
# de log por segundo. Emitir um sinal Qt por evento, cruzando threads, tem um custo perceptível
# e deixava a interface travando. Em vez disso, o motor só enfileira; um QTimer no thread da
# GUI drena o que se acumulou a cada FLUSH_INTERVAL_MS e atualiza a tabela em lote.
FLUSH_INTERVAL_MS = 200


class AppContext(QObject):
    log_added = Signal(list)
    log_updated = Signal(list)
    status_changed = Signal(bool, str)
    config_changed = Signal()
    egress_ip_changed = Signal(str, str, str)  # profile_id, ip anterior ("" se é o primeiro), ip atual

    def __init__(self) -> None:
        super().__init__()
        self.config: AppConfig = load_config()
        self.log_store = LogStore(retention_days=self.config.settings.log_retention_days)
        self.engine = ProxyEngine(self.config, self.log_store)
        self.engine.on_status_change = self._on_status
        self.engine.on_egress_ip_change = self._on_egress_ip_change
        self.log_store.subscribe(self._on_log_event)

        # Último IP de saída conhecido por perfil (profile.id -> (ip_anterior, ip_atual)),
        # carregado do disco pra sobreviver a fechar/reabrir o app — widgets criados depois do
        # fato (ex.: ao trocar a seleção no atalho do Dashboard) consultam esse estado direto,
        # sem esperar o próximo sinal. Alimenta o motor de volta (só o IP "atual" de cada perfil)
        # pra ele continuar comparando contra o valor real anterior, em vez de tratar a primeira
        # verificação pós-reabertura como se não houvesse histórico nenhum.
        self.egress_ip_state: dict[str, tuple[str, str]] = load_egress_ip_state()
        self.engine.seed_egress_ip_state(
            {pid: current for pid, (_previous, current) in self.egress_ip_state.items()})

        self._pending_lock = threading.Lock()
        self._pending_added: list[LogEntry] = []
        self._pending_updated: dict[str, LogEntry] = {}

        self.log_model = LogTableModel()
        self.log_model.load_initial(list(reversed(self.log_store.recent())))
        self.log_added.connect(self.log_model.add_entries)
        self.log_updated.connect(self.log_model.update_entries)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_pending)
        self._flush_timer.start()

        if self.config.settings.system_integration_enabled:
            # Se a última sessão terminou de forma abrupta (crash, "Finalizar tarefa" etc.) com a
            # integração ligada, o Windows/Linux pode ter ficado apontando para um PAC que não
            # existe mais (o motor ainda nem subiu neste momento) — isso deixa QUALQUER conexão
            # de rede lenta até alguém remover manualmente. Como rede de segurança, limpamos essa
            # configuração agora (síncrono: acontece antes da janela aparecer); ela volta sozinha
            # assim que o motor for iniciado de novo.
            self._sync_system_proxy(applying=False)

    def _on_log_event(self, event: str, entry: LogEntry) -> None:
        # Chamado na thread do motor: só enfileira, sem tocar em nada do Qt aqui.
        with self._pending_lock:
            if event == "added":
                self._pending_added.append(entry)
            else:
                self._pending_updated[entry.id] = entry

    def _flush_pending(self) -> None:
        with self._pending_lock:
            if not self._pending_added and not self._pending_updated:
                return
            added, self._pending_added = self._pending_added, []
            updated = list(self._pending_updated.values())
            self._pending_updated = {}
        if added:
            self.log_added.emit(added)
        if updated:
            self.log_updated.emit(updated)

    def _on_egress_ip_change(self, profile_id: str, previous_ip: str, current_ip: str) -> None:
        # Chamado na thread do motor (mesma ressalva de _on_log_event): Signal.emit atravessa
        # pra a thread da GUI sozinho (conexão automática do Qt), então basta guardar o estado e
        # emitir — nada de tocar em widgets aqui. Persiste a cada mudança (não só ao fechar o
        # app): mudanças de IP são raras (minutos/horas entre elas, não por conexão), então o
        # custo é insignificante, e assim o histórico sobrevive até a um encerramento abrupto.
        self.egress_ip_state[profile_id] = (previous_ip, current_ip)
        save_egress_ip_state(self.egress_ip_state)
        self.egress_ip_changed.emit(profile_id, previous_ip, current_ip)

    def _on_status(self, running: bool, message: str) -> None:
        self.status_changed.emit(running, message)
        # A integração com o sistema (PAC) segue o motor automaticamente: se ligarmos o proxy
        # do sistema e depois o motor for parado (ou travar) sem desligar essa configuração, o
        # SO fica preso apontando para um proxy morto e a internet inteira parece lenta. Ligando
        # e desligando junto com o motor, esse estado inconsistente nunca acontece.
        if self.config.settings.system_integration_enabled:
            self._sync_system_proxy(applying=running)

    def _sync_system_proxy(self, applying: bool) -> None:
        """Chamada de forma SÍNCRONA e bloqueante, de propósito.

        Isso já foi uma thread em background (para não travar nada). O problema: se o usuário
        parasse o motor e fechasse o app logo em seguida, o processo podia terminar (matando a
        thread) antes da chamada de registro/subprocess completar — deixando o Windows/Linux
        preso apontando para um PAC morto mesmo com o app "tendo removido" a configuração.
        É seguro bloquear aqui: essa função só é chamada bem no início do motor (antes de haver
        qualquer conexão para atender) ou bem no fim (depois de todas as conexões já terem sido
        encerradas em _shutdown), então uma pausa de alguns milissegundos não afeta tráfego real.
        """
        settings = self.config.settings
        try:
            if applying:
                system_integration.apply_system_proxy(
                    system_integration.pac_url(settings.pac_port), settings.http_port)
            else:
                system_integration.remove_system_proxy()
        except Exception:
            pass

    def save(self) -> None:
        save_config(self.config)

    def apply_config_changes(self) -> None:
        """Chamar depois de qualquer edição em self.config (proxies/regras/settings)."""
        self.engine.update_config(self.config)
        self.log_store.retention_days = self.config.settings.log_retention_days
        self._prune_egress_ip_state()
        self.save()
        self.config_changed.emit()

    def _prune_egress_ip_state(self) -> None:
        """Descarta o histórico de IP guardado para perfis que não existem mais — senão um
        perfil apagado deixaria uma entrada órfã no arquivo pra sempre."""
        known_ids = {p.id for p in self.config.proxies}
        orphaned = set(self.egress_ip_state) - known_ids
        if orphaned:
            for profile_id in orphaned:
                del self.egress_ip_state[profile_id]
            save_egress_ip_state(self.egress_ip_state)

    def apply_settings_live(self) -> tuple[bool, str]:
        """Como apply_config_changes(), mas pra mudanças de porta/modo transparente com o motor
        JÁ rodando: em vez de update_config() (que só atualiza o estado em memória, sem tocar
        nos listeners), troca só o socket da porta que mudou — sem parar o motor nem derrubar
        conexões que não têm nada a ver com a porta trocada. Só funciona com o motor rodando;
        quem chama continua responsável por cair para apply_config_changes() quando ele estiver
        parado (ali update_config() já basta, os listeners nem existem ainda)."""
        ok, message = self.engine.apply_settings_live(self.config)
        self.log_store.retention_days = self.config.settings.log_retention_days
        self.save()
        self.config_changed.emit()
        return ok, message
