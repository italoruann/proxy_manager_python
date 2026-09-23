"""Persistência de configuração: perfis de proxy, regras (texto bruto) e preferências gerais."""
from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from platformdirs import user_config_dir, user_data_dir

try:
    import keyring
except ImportError:  # pragma: no cover - keyring é dependência declarada, mas ficamos resilientes
    keyring = None  # type: ignore[assignment]

APP_NAME = "ProxyManager"
APP_AUTHOR = "ProxyManager"

# Valor gravado em "password" no config.json quando a senha real mora no cofre de credenciais do
# SO (Windows Credential Manager / Secret Service no Linux) em vez de texto puro no arquivo.
_KEYRING_MARKER = "\u0000keyring\u0000"
_KEYRING_SERVICE = "ProxyManager"

DEFAULT_RULES_TEXT = """\
# Regras de roteamento — avaliadas de cima para baixo, a primeira que casar vence.
# Sintaxe:
#   apps: processo1.exe, processo2      -> escopo por aplicativo (opcional; "apps: *" volta a valer para todos)
#   padrao.dominio.com                  -> sem sufixo = vai pelo proxy padrao
#   padrao.dominio.com +direct          -> vai direto (sem passar pelo proxy)
#   padrao.dominio.com +proxy:nome      -> vai por um perfil de proxy especifico
#   padrao.dominio.com +block           -> bloqueia a conexao

*.example.com
*.example.org

*.paypal.com +direct
*.stripe.com +direct
"""


def config_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class ProxyProfile:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "Meu Proxy"
    type: str = "socks5"  # "socks5" | "http"
    host: str = ""
    port: int = 1080
    username: str = ""
    password: str = ""
    enabled: bool = True
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ProxyProfile":
        known = {f: data.get(f) for f in ProxyProfile.__dataclass_fields__ if f in data}
        return ProxyProfile(**known)


@dataclass
class AppDefinition:
    """Um aplicativo cadastrado pelo usuário (nome amigável + caminho do executável), para
    referenciar nas regras sem precisar decorar o nome exato do processo."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "Novo aplicativo"
    executable_path: str = ""

    @property
    def process_name(self) -> str:
        return os.path.basename(self.executable_path) if self.executable_path else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppDefinition":
        known = {f: data.get(f) for f in AppDefinition.__dataclass_fields__ if f in data}
        return AppDefinition(**known)


@dataclass
class Settings:
    socks_port: int = 58080
    http_port: int = 58081
    pac_port: int = 58090
    system_integration_enabled: bool = False
    default_action: str = "direct"  # "direct" | "block"
    log_retention_days: int = 14
    start_minimized: bool = False
    transparent_mode_enabled: bool = False
    transparent_port: int = 58095

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Settings":
        known = {f: data.get(f) for f in Settings.__dataclass_fields__ if f in data}
        return Settings(**known)


@dataclass
class AppConfig:
    proxies: list[ProxyProfile] = field(default_factory=list)
    apps: list[AppDefinition] = field(default_factory=list)
    rules_text: str = DEFAULT_RULES_TEXT
    settings: Settings = field(default_factory=Settings)

    def default_proxy(self) -> Optional[ProxyProfile]:
        for p in self.proxies:
            if p.is_default and p.enabled:
                return p
        for p in self.proxies:
            if p.enabled:
                return p
        return None

    def find_proxy(self, name: str) -> Optional[ProxyProfile]:
        for p in self.proxies:
            if p.name == name:
                return p
        return None

    def ensure_single_default(self) -> None:
        """Garante que só exista um perfil marcado como padrão (o primeiro encontrado vence)."""
        seen_default = False
        for p in self.proxies:
            if p.is_default:
                if seen_default:
                    p.is_default = False
                else:
                    seen_default = True
        if not seen_default and self.proxies:
            self.proxies[0].is_default = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proxies": [p.to_dict() for p in self.proxies],
            "apps": [a.to_dict() for a in self.apps],
            "rules_text": self.rules_text,
            "settings": self.settings.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AppConfig":
        proxies = [ProxyProfile.from_dict(p) for p in data.get("proxies", [])]
        apps = [AppDefinition.from_dict(a) for a in data.get("apps", [])]
        rules_text = data.get("rules_text", DEFAULT_RULES_TEXT)
        settings = Settings.from_dict(data.get("settings", {}))
        return AppConfig(proxies=proxies, apps=apps, rules_text=rules_text, settings=settings)


def _keyring_set(profile_id: str, password: str) -> bool:
    """Tenta gravar a senha no cofre do SO. Retorna False (sem levantar) se o keyring não estiver
    instalado ou não houver backend disponível (ex.: Linux headless sem Secret Service) — quem
    chama deve então manter a senha em texto puro no JSON como rede de segurança."""
    if keyring is None:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, profile_id, password)
        return True
    except Exception:
        return False


def _keyring_get(profile_id: str) -> Optional[str]:
    if keyring is None:
        return None
    try:
        return keyring.get_password(_KEYRING_SERVICE, profile_id)
    except Exception:
        return None


def _keyring_delete(profile_id: str) -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(_KEYRING_SERVICE, profile_id)
    except Exception:
        pass  # perfil pode nunca ter tido senha guardada no keyring; sem problema


def _previous_proxy_ids(path: Path) -> set[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {p["id"] for p in data.get("proxies", []) if p.get("id")}
    except (OSError, json.JSONDecodeError, KeyError):
        return set()


def _backup_path(path: Path) -> Path:
    return path.with_suffix(".json.bak")


def _try_load(path: Path) -> Optional[AppConfig]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        cfg = AppConfig.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return None
    for profile in cfg.proxies:
        if profile.password == _KEYRING_MARKER:
            profile.password = _keyring_get(profile.id) or ""
    return cfg


def load_config() -> AppConfig:
    path = config_file_path()
    cfg = _try_load(path)
    if cfg is not None:
        return cfg

    # config.json não existe ou está corrompido/ilegível: tenta o backup automático (gravado a
    # cada save_config, antes de sobrescrever) antes de desistir e cair no padrão de fábrica —
    # é a rede de segurança contra um save malsucedido, um arquivo corrompido por uma queda de
    # energia, etc.
    backup = _try_load(_backup_path(path))
    if backup is not None:
        save_config(backup)  # promove o backup de volta a config.json válido
        return backup

    cfg = AppConfig()
    save_config(cfg)
    return cfg


def save_config(cfg: AppConfig) -> None:
    path = config_file_path()
    tmp_path = path.with_suffix(".json.tmp")

    removed_proxy_ids = _previous_proxy_ids(path) - {p.id for p in cfg.proxies}

    data = cfg.to_dict()
    for proxy_data, profile in zip(data["proxies"], cfg.proxies):
        # Só tira a senha do JSON se o keyring realmente aceitou guardá-la — senão o save
        # continuaria de pé, mas a senha teria sumido de vez (nem no arquivo, nem no cofre).
        if profile.password and _keyring_set(profile.id, profile.password):
            proxy_data["password"] = _KEYRING_MARKER

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    if path.exists():
        try:
            shutil.copy2(path, _backup_path(path))
        except OSError:
            pass  # sem backup desta vez não deve impedir o save de valer.

    os.replace(tmp_path, path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # chmod não se aplica da mesma forma no Windows; sem problema.

    for profile_id in removed_proxy_ids:
        _keyring_delete(profile_id)
