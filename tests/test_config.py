"""Testes de persistência: round-trip básico, backup automático e recuperação a partir dele
quando o config.json principal está corrompido ou ausente."""
import json

import pytest

from proxy_manager.core import config as config_module
from proxy_manager.core.config import (
    AppConfig,
    AppDefinition,
    ProxyProfile,
    Settings,
    load_config,
    save_config,
)


@pytest.fixture()
def isolated_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(config_module, "data_dir", lambda: tmp_path)
    return tmp_path


class FakeKeyring:
    """Substitui o keyring real do SO nos testes: mesma interface, guardada em memória. Sem
    isso, os testes gravariam segredos de verdade no Credential Manager/Secret Service da
    máquina que roda a suíte."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture()
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(config_module, "keyring", fake)
    return fake


@pytest.fixture(autouse=True)
def _isolate_real_keyring(monkeypatch):
    """Autouse: mesmo os testes que não pedem `fake_keyring` explicitamente não devem tocar no
    keyring real da máquina — por padrão simula "sem backend disponível" (como Linux headless),
    que é justamente o caminho de fallback que save_config/load_config precisam suportar."""
    monkeypatch.setattr(config_module, "keyring", None)


def _sample_config() -> AppConfig:
    proxy = ProxyProfile(name="Trabalho", type="socks5", host="proxy.exemplo.com", port=1080,
                          username="italo", password="segredo", is_default=True)
    settings = Settings(default_action="block", log_retention_days=30)
    return AppConfig(proxies=[proxy], rules_text="*.exemplo.com +direct\n", settings=settings)


def test_save_and_load_round_trip(isolated_config_dir):
    cfg = _sample_config()
    save_config(cfg)

    loaded = load_config()
    assert len(loaded.proxies) == 1
    assert loaded.proxies[0].host == "proxy.exemplo.com"
    assert loaded.proxies[0].password == "segredo"
    assert loaded.rules_text == "*.exemplo.com +direct\n"
    assert loaded.settings.default_action == "block"
    assert loaded.settings.log_retention_days == 30


def test_save_creates_backup_of_previous_version(isolated_config_dir):
    save_config(_sample_config())  # primeira versão, ainda sem backup
    backup_path = isolated_config_dir / "config.json.bak"
    assert not backup_path.exists()

    second = _sample_config()
    second.proxies[0].name = "Trabalho v2"
    save_config(second)  # agora deve ter feito backup da versão anterior

    assert backup_path.exists()
    with open(backup_path, encoding="utf-8") as fh:
        backed_up = json.load(fh)
    assert backed_up["proxies"][0]["name"] == "Trabalho"  # a versão ANTERIOR, não a nova


def test_load_recovers_from_backup_when_main_file_is_corrupted(isolated_config_dir):
    save_config(_sample_config())
    save_config(_sample_config())  # garante que exista um .bak válido

    config_path = isolated_config_dir / "config.json"
    config_path.write_text("{ isso não é json válido", encoding="utf-8")

    recovered = load_config()
    assert len(recovered.proxies) == 1
    assert recovered.proxies[0].host == "proxy.exemplo.com"

    # a recuperação também deve ter promovido o backup de volta a um config.json válido
    with open(config_path, encoding="utf-8") as fh:
        json.load(fh)  # não deve levantar exceção


def test_load_falls_back_to_defaults_when_nothing_is_recoverable(isolated_config_dir):
    cfg = load_config()
    assert cfg.proxies == []
    assert cfg.rules_text  # o texto de exemplo padrão


def test_app_definition_process_name_from_executable_path():
    app = AppDefinition(name="Chrome", executable_path=r"C:\Program Files\Google\Chrome\chrome.exe")
    assert app.process_name == "chrome.exe"


def test_app_definitions_round_trip(isolated_config_dir):
    cfg = _sample_config()
    cfg.apps.append(AppDefinition(name="Chrome", executable_path=r"C:\Chrome\chrome.exe"))
    save_config(cfg)

    loaded = load_config()
    assert len(loaded.apps) == 1
    assert loaded.apps[0].name == "Chrome"
    assert loaded.apps[0].process_name == "chrome.exe"


def test_password_falls_back_to_plaintext_json_when_no_keyring_backend(isolated_config_dir):
    """Sem backend de keyring disponível (Linux headless, etc.) a senha continua indo pro JSON,
    exatamente como antes — é a rede de segurança que evita perder a credencial."""
    save_config(_sample_config())

    with open(isolated_config_dir / "config.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    assert raw["proxies"][0]["password"] == "segredo"

    assert load_config().proxies[0].password == "segredo"


def test_password_is_moved_to_keyring_when_backend_available(isolated_config_dir, fake_keyring):
    save_config(_sample_config())

    with open(isolated_config_dir / "config.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    proxy_id = raw["proxies"][0]["id"]
    assert raw["proxies"][0]["password"] != "segredo"  # não fica mais em texto puro no arquivo
    assert fake_keyring.store[("ProxyManager", proxy_id)] == "segredo"

    loaded = load_config()
    assert loaded.proxies[0].password == "segredo"  # continua utilizável em memória


def test_removing_a_proxy_deletes_its_keyring_entry(isolated_config_dir, fake_keyring):
    cfg = _sample_config()
    save_config(cfg)
    proxy_id = cfg.proxies[0].id
    assert ("ProxyManager", proxy_id) in fake_keyring.store

    cfg.proxies = []
    save_config(cfg)

    assert ("ProxyManager", proxy_id) not in fake_keyring.store
