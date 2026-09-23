"""Smoke test da GUI: sobe a janela principal (offscreen) e navega por todas as páginas,
exercitando as ações mais comuns, para pegar erros de import/layout/sinal sem precisar de
interação visual manual."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import pytest

TMP_CONFIG_DIR = tempfile.mkdtemp(prefix="proxy_manager_test_")
# No Windows, platformdirs resolve a pasta local via ctypes/registro (SHGetKnownFolderPath),
# IGNORANDO a variável de ambiente LOCALAPPDATA — só respeita o override oficial abaixo.
# Sem isso, os testes de GUI acabariam lendo/escrevendo na config REAL do usuário.
os.environ["WIN_PD_OVERRIDE_LOCAL_APPDATA"] = TMP_CONFIG_DIR
os.environ["WIN_PD_OVERRIDE_APPDATA"] = TMP_CONFIG_DIR
os.environ["XDG_CONFIG_HOME"] = TMP_CONFIG_DIR
os.environ["XDG_DATA_HOME"] = TMP_CONFIG_DIR

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from proxy_manager.core.config import ProxyProfile
from proxy_manager.core.logstore import LogEntry
from proxy_manager.core.rules import RuleSet
from proxy_manager.gui.app_context import AppContext
from proxy_manager.gui.main_window import MainWindow
from proxy_manager.gui.pages.proxies_page import ProxiesPage

# Evita que caixas de diálogo modais (QMessageBox) travem o teste esperando um clique humano.
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(app):
    ctx = AppContext()
    win = MainWindow(ctx)
    yield win
    ctx.engine.stop()
    win.close()


def test_window_builds_and_navigates_all_pages(window):
    assert window.stack.count() == 5
    for i in range(window.stack.count()):
        window.nav_buttons[i].click()
        assert window.stack.currentIndex() == i


def test_add_and_remove_proxy_profile(window):
    window.nav_buttons[1].click()
    page = window.proxies_page
    initial_count = len(page.ctx.config.proxies)

    page._on_new()
    assert len(page.ctx.config.proxies) == initial_count + 1

    page.host_edit.setText("proxy.example.com")
    page.port_spin.setValue(1080)
    page._on_save()
    assert page.ctx.config.proxies[-1].host == "proxy.example.com"


def test_proxies_page_form_is_editable_on_open_when_a_profile_already_exists(app):
    """Regressão: __init__ chamava _set_form_enabled(False) logo depois de _reload_list() —
    que, quando já existe pelo menos um perfil salvo (o caso normal de reabrir o app), seleciona
    a primeira linha sozinho e HABILITA o formulário via _on_selection_changed. Essa chamada
    extra desfazia a habilitação na hora, deixando os campos travados pro primeiro perfil logo
    na abertura da página (só destravava criando e apagando um perfil novo, porque esse fluxo
    não passa por aquela linha extra)."""
    ctx = AppContext()
    # insert(0, ...), não append(...): outros testes deste módulo compartilham o mesmo diretório
    # de config (TMP_CONFIG_DIR) e podem já ter salvo outros perfis — precisa ser o primeiro da
    # lista de propósito, já que é exatamente a linha 0 que _reload_list() auto-seleciona.
    ctx.config.proxies.insert(0, ProxyProfile(name="Já existente", host="proxy.exemplo.com"))

    page = ProxiesPage(ctx)

    assert page.host_edit.isEnabled()
    assert page.name_edit.isEnabled()
    assert page.save_btn.isEnabled()
    assert page.host_edit.text() == "proxy.exemplo.com"


def test_rules_table_round_trip(window):
    window.nav_buttons[2].click()
    page = window.rules_page
    initial_rows = page.table.rowCount()

    page._on_add_row()
    page.table.item(initial_rows, 2).setText("*.example.com")
    page._on_save_table()

    assert "*.example.com" in page.ctx.config.rules_text


def test_add_app_catchall_button_creates_wildcard_rule(window):
    """O botão '+ App com proxy padrão' precisa criar uma regra alvo='*' pronta para o usuário
    só digitar o nome do executável — atalho para 'todo o Chrome pelo proxy'."""
    window.nav_buttons[2].click()
    page = window.rules_page
    row = page.table.rowCount()

    page._on_add_app_catchall()
    assert page.table.item(row, 2).text() == "*"

    page.table.item(row, 1).setText("chrome.exe")
    page.table.setCurrentCell(row, 2)  # sai do modo de edição da célula de Aplicativos

    rule_set = page._rule_set_from_table()
    new_rule = rule_set.rules[-1]
    assert new_rule.apps == ["chrome.exe"]
    assert new_rule.pattern == "*"
    assert new_rule.action == "proxy"


def test_add_app_button_disabled_until_executable_chosen(window):
    """Regressão: um usuário clicou em 'Procurar...' mas nunca em '+ Adicionar' (não ficava
    óbvio que eram dois passos), então o app nunca foi salvo de verdade. O botão agora começa
    desabilitado e só liga quando há um caminho de executável preenchido."""
    window.nav_buttons[2].click()
    page = window.rules_page
    assert not page.add_app_def_btn.isEnabled()

    page.app_path_edit.setText(r"C:\Chrome\chrome.exe")
    assert page.add_app_def_btn.isEnabled()

    page.app_path_edit.clear()
    assert not page.add_app_def_btn.isEnabled()


def test_add_app_definition_appears_in_apps_table(window):
    window.nav_buttons[2].click()
    page = window.rules_page
    initial_rows = page.apps_table.rowCount()

    page.app_name_edit.setText("Chrome")
    page.app_path_edit.setText(r"C:\Chrome\chrome.exe")
    page._on_add_app_definition()

    assert page.apps_table.rowCount() == initial_rows + 1
    assert page.ctx.config.apps[-1].name == "Chrome"
    assert page.ctx.config.apps[-1].process_name == "chrome.exe"
    # os campos do formulário devem ser limpos após adicionar, prontos pro próximo cadastro
    assert page.app_name_edit.text() == ""
    assert page.app_path_edit.text() == ""


def test_add_app_definition_creates_catchall_rule_when_none_exists(window):
    """Regressão: cadastrar um app sem nenhuma regra pra ele precisa capturar TODO o tráfego
    daquele app pelo proxy automaticamente (igual ao Proxifier) — não pode ficar em silêncio
    passando direto até o usuário escrever uma regra manualmente."""
    window.nav_buttons[2].click()
    page = window.rules_page

    page.app_name_edit.setText("Chrome")
    page.app_path_edit.setText(r"C:\Chrome\chrome.exe")
    page._on_add_app_definition()

    rule_set = RuleSet.parse(page.ctx.config.rules_text)
    match = rule_set.match("chrome.exe", r"C:\Chrome\chrome.exe", "qualquerdominio.com", None,
                            default_action="direct")
    assert match.action_kind == "proxy"


def test_add_app_definition_does_not_duplicate_existing_rule(window):
    window.nav_buttons[2].click()
    page = window.rules_page

    page.ctx.config.rules_text = "apps: chrome.exe\n*.paypal.com +direct\n"
    page.ctx.apply_config_changes()

    page.app_name_edit.setText("Chrome")
    page.app_path_edit.setText(r"C:\Chrome\chrome.exe")
    page._on_add_app_definition()

    rule_set = RuleSet.parse(page.ctx.config.rules_text)
    chrome_rules = [r for r in rule_set.rules if "chrome.exe" in r.apps]
    assert len(chrome_rules) == 1  # não deve ter criado uma segunda regra pra esse app


def test_add_app_catchall_offers_registered_apps_instead_of_free_typing(window, monkeypatch):
    """Com pelo menos um aplicativo já cadastrado, o botão '+ App com proxy padrão' deve deixar
    escolher ele numa lista, em vez de abrir a célula para digitação manual."""
    from PySide6.QtWidgets import QInputDialog

    window.nav_buttons[2].click()
    page = window.rules_page

    page.app_name_edit.setText("Chrome")
    page.app_path_edit.setText(r"C:\Chrome\chrome.exe")
    page._on_add_app_definition()

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: (a[3][0], True)))

    row = page.table.rowCount()
    page._on_add_app_catchall()

    assert page.table.item(row, 1).text() == "chrome.exe"
    assert page.table.item(row, 2).text() == "*"


def test_logs_page_filters_do_not_crash(window):
    window.nav_buttons[3].click()
    page = window.logs_page
    page.search_edit.setText("example")
    page.action_combo.setCurrentIndex(1)
    page.protocol_combo.setCurrentIndex(1)
    page.search_edit.setText("")


def test_logs_page_columns_are_sortable(window):
    """Regressão: a tabela de logs nunca tinha setSortingEnabled(True) — clicar num cabeçalho de
    coluna não fazia absolutamente nada. E, porque DisplayRole é sempre uma string já formatada
    ("1.2 KB", "230 ms"), ordenar por ela dava ordem alfabética em vez de numérica."""
    window.nav_buttons[3].click()
    page = window.logs_page
    assert page.table.isSortingEnabled()

    for host, duration_ms, bytes_sent in (("a.com", 1453, 800), ("b.com", 50, 1200), ("c.com", 200, 5000)):
        page.ctx.log_model.add_entries([LogEntry(dst_host=host, duration_ms=duration_ms,
                                                   bytes_sent=bytes_sent, status="concluida")])

    def column_values(col: int) -> list[str]:
        return [page.proxy_model.data(page.proxy_model.index(row, col))
                for row in range(page.proxy_model.rowCount())]

    page.table.sortByColumn(11, Qt.SortOrder.AscendingOrder)  # Duração
    assert column_values(11) == ["50 ms", "200 ms", "1453 ms"]

    page.table.sortByColumn(11, Qt.SortOrder.DescendingOrder)
    assert column_values(11) == ["1453 ms", "200 ms", "50 ms"]

    page.table.sortByColumn(9, Qt.SortOrder.AscendingOrder)  # Enviado (bytes)
    assert column_values(9) == ["800 B", "1.2 KB", "4.9 KB"]


def test_settings_page_toggles(window):
    window.nav_buttons[4].click()
    page = window.settings_page
    page.default_action_combo.setCurrentIndex(1)
    assert page.ctx.config.settings.default_action == "block"
    page.retention_spin.setValue(30)
    assert page.ctx.config.settings.log_retention_days == 30


def test_engine_start_stop_from_dashboard(window):
    window.nav_buttons[0].click()
    page = window.dashboard_page
    page.ctx.config.settings.socks_port = 58480
    page.ctx.config.settings.http_port = 58481
    page.ctx.config.settings.pac_port = 58490

    page._on_toggle_clicked()
    QTest.qWait(300)
    assert page.ctx.engine.is_running()

    page._on_toggle_clicked()
    QTest.qWait(300)
    assert not page.ctx.engine.is_running()


class _FakeCloseEvent:
    def __init__(self):
        self.accepted = False
        self.ignored = False

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def test_settings_page_changes_port_without_stopping_engine(window):
    """Regressão: trocar a porta nas Configurações com o motor rodando não pode exigir parar e
    religar ele (isso derrubaria toda conexão ativa, mesmo em portas não relacionadas à que
    mudou) — precisa trocar só o listener daquela porta específica, ao vivo."""
    window.nav_buttons[0].click()
    dashboard = window.dashboard_page
    dashboard.ctx.config.settings.socks_port = 58910
    dashboard.ctx.config.settings.http_port = 58911
    dashboard.ctx.config.settings.pac_port = 58912

    dashboard._on_toggle_clicked()
    QTest.qWait(300)
    assert dashboard.ctx.engine.is_running()

    window.nav_buttons[4].click()
    page = window.settings_page
    page.socks_port_spin.setValue(58910)  # sem mudança
    page.http_port_spin.setValue(58911)  # sem mudança
    page.pac_port_spin.setValue(58913)  # só o PAC muda
    page._on_save_ports()
    QTest.qWait(200)

    # o motor nunca parou (é exatamente o que "trocar sem derrubar" significa)
    assert page.ctx.engine.is_running()
    assert page.ctx.config.settings.pac_port == 58913


def test_close_without_tray_stops_engine_and_quits_app(window, app, monkeypatch):
    """Regressão: sem bandeja do sistema (GNOME sem extensão, por exemplo), só esconder a janela
    ao fechar deixaria o processo rodando sem nenhum jeito de reabri-lo. Fechar precisa fechar
    de verdade."""
    window.tray = None
    stop_calls = []
    monkeypatch.setattr(window.ctx.engine, "stop", lambda: stop_calls.append(True))
    quit_calls = []
    monkeypatch.setattr(app, "quit", lambda: quit_calls.append(True))

    event = _FakeCloseEvent()
    window.closeEvent(event)

    assert stop_calls == [True]
    assert quit_calls == [True]
    assert event.accepted is True
    assert event.ignored is False


def test_close_with_tray_hides_window_instead_of_quitting(window, monkeypatch):
    """Com bandeja disponível, o comportamento de sempre continua valendo: esconder, não fechar."""
    hide_calls = []
    monkeypatch.setattr(window, "hide", lambda: hide_calls.append(True))
    message_calls = []

    class _FakeTray:
        def showMessage(self, *args, **kwargs):
            message_calls.append((args, kwargs))

    window.tray = _FakeTray()

    event = _FakeCloseEvent()
    window.closeEvent(event)

    assert hide_calls == [True]
    assert message_calls
    assert event.ignored is True
    assert event.accepted is False


def test_system_integration_follows_engine_lifecycle(window, monkeypatch):
    """Regressão: a integração com o sistema (PAC) precisa ligar/desligar sozinha junto com o
    motor, senão o SO fica preso apontando para um proxy morto depois que o motor para, deixando
    a internet inteira lenta.

    Sem QTest.qWait() de propósito: a remoção precisa ter acontecido de forma SÍNCRONA, antes de
    engine.stop() retornar. Uma versão antiga disparava isso numa thread em background — se o
    processo fosse encerrado logo em seguida (fechar o app assim que parar o motor), a thread
    podia morrer antes de terminar e a configuração do sistema nunca era revertida de verdade.
    Um teste com qWait(300) não pegaria essa regressão, porque a thread tinha tempo de sobra
    para terminar durante o teste (e nenhum tempo de sobra no cenário real do usuário)."""
    from proxy_manager.core import system_integration

    calls = []
    monkeypatch.setattr(system_integration, "apply_system_proxy",
                         lambda url, port: calls.append(("apply", url, port)) or (True, "ok"))
    monkeypatch.setattr(system_integration, "remove_system_proxy",
                         lambda: calls.append(("remove",)) or (True, "ok"))

    ctx = window.ctx
    ctx.config.settings.system_integration_enabled = True
    ctx.config.settings.socks_port = 58680
    ctx.config.settings.http_port = 58681
    ctx.config.settings.pac_port = 58690

    ctx.engine.start()
    assert any(c[0] == "apply" for c in calls), "deveria aplicar o proxy do sistema antes de start() retornar"

    calls.clear()
    ctx.engine.stop()
    assert any(c[0] == "remove" for c in calls), "deveria remover o proxy do sistema antes de stop() retornar"
