"""Aponta os navegadores do Linux para o nosso PAC direto, sem depender do ambiente gráfico.

O proxy "do sistema" no Linux não existe de verdade: o GNOME guarda no gsettings, o KDE no
kioslaverc, Xfce/LXQt/i3/Hyprland em lugar nenhum — e cada navegador lê de um jeito (o Firefox só
olha o gsettings, o Chromium só olha o gsettings/kioslaverc no GNOME/KDE e nada nos outros). Aqui
configuramos o próprio navegador, o que funciona igual em qualquer distro e ambiente:

- Firefox (e derivados, inclusive Flatpak/Snap): bloco no user.js de cada perfil. Os valores
  anteriores ficam guardados no bloco e são restaurados ao remover.
- Chrome/Chromium/Edge/Brave/Vivaldi/Opera (inclusive Flatpak/Snap): cópia do atalho .desktop em
  ~/.local/share/applications (que tem prioridade sobre o do sistema) com --proxy-pac-url. Ela
  fica quando o motor para (sem o motor o PAC não responde e o navegador conecta direto) e só é
  apagada ao desativar a integração, com o navegador fechado.

Se o app morrer sem remover, os dois navegadores caem para conexão direta quando o PAC não
responde — a internet continua funcionando.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import system_integration as si

_ERRORS = (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError)

# ---------------------------------------------------------------------------
# Firefox
# ---------------------------------------------------------------------------

# Relativos à HOME. Firefox 147+ cria perfis novos em ~/.config/mozilla/firefox (XDG).
_FIREFOX_ROOTS = (
    ".mozilla/firefox",
    ".config/mozilla/firefox",
    ".var/app/org.mozilla.firefox/.mozilla/firefox",
    ".var/app/org.mozilla.firefox/config/mozilla/firefox",
    "snap/firefox/common/.mozilla/firefox",
    ".librewolf",
    ".var/app/io.gitlab.librewolf-community/.librewolf",
    ".waterfox",
    ".floorp",
    ".var/app/one.ablaze.floorp/.floorp",
    ".zen",
    ".var/app/app.zen_browser.zen/.zen",
)

_BLOCK_BEGIN = "// >>> Proxy Manager (gerado automaticamente, não edite este bloco)"
_BLOCK_END = "// <<< Proxy Manager"
_ORIGINAL_PREFIX = "// original: "
_FIREFOX_PREFS = ("network.proxy.type", "network.proxy.autoconfig_url")
_FIREFOX_DEFAULTS = {"network.proxy.type": "5", "network.proxy.autoconfig_url": '""'}
_PREF_RE = re.compile(r'^\s*user_pref\("([^"]+)",\s*(.*?)\);\s*$')


def firefox_profiles() -> list[Path]:
    home = si._desktop_home()
    profiles: list[Path] = []
    for root in _FIREFOX_ROOTS:
        base = home / root
        if not base.is_dir():
            continue
        profiles.extend(p for p in sorted(base.iterdir()) if (p / "prefs.js").is_file())
    return profiles


def apply_firefox(profile: Path, url: str) -> None:
    user_js = profile / "user.js"
    block, rest = _split_block(si._read_user_file(user_js))
    if block is not None:
        originals = _block_originals(block)
    else:
        current = _read_prefs(si._read_user_file(profile / "prefs.js"))
        originals = {name: current.get(name) for name in _FIREFOX_PREFS}
    prefs = {"network.proxy.type": "2", "network.proxy.autoconfig_url": json.dumps(url)}
    si._write_user_file(user_js, _join(rest, _firefox_block(prefs, originals)))


def remove_firefox(profile: Path) -> bool:
    user_js = profile / "user.js"
    block, rest = _split_block(si._read_user_file(user_js))
    if block is None:
        return False
    originals = _block_originals(block)
    if _firefox_running(profile):
        # Ao fechar, o Firefox regrava o prefs.js com o PAC que está em memória; um bloco de
        # restauração no user.js vence isso na próxima abertura (e some na próxima remoção).
        restore = {name: value if value is not None else _FIREFOX_DEFAULTS[name]
                   for name, value in originals.items()}
        si._write_user_file(user_js, _join(rest, _firefox_block(restore, originals)))
        return True
    if rest.strip():
        si._write_user_file(user_js, rest.rstrip("\n") + "\n")
    else:
        si._delete_user_file(user_js)
    prefs_js = profile / "prefs.js"
    si._write_user_file(prefs_js, _set_prefs(si._read_user_file(prefs_js), originals))
    return True


def _firefox_running(profile: Path) -> bool:
    # O symlink "lock" só existe enquanto o Firefox está com o perfil aberto.
    return os.path.lexists(profile / "lock")


def _split_block(text: str) -> tuple[list[str] | None, str]:
    lines = text.splitlines()
    begin = next((i for i, line in enumerate(lines) if line.startswith(_BLOCK_BEGIN[:20])), None)
    if begin is None:
        return None, text
    end = next((i for i in range(begin, len(lines)) if lines[i].startswith(_BLOCK_END)), len(lines) - 1)
    rest = lines[:begin] + lines[end + 1:]
    return lines[begin:end + 1], "\n".join(rest) + ("\n" if rest else "")


def _block_originals(block: list[str]) -> dict[str, str | None]:
    for line in block:
        if line.startswith(_ORIGINAL_PREFIX):
            try:
                saved = json.loads(line[len(_ORIGINAL_PREFIX):])
                return {name: saved.get(name) for name in _FIREFOX_PREFS}
            except (ValueError, AttributeError):
                break
    return {name: None for name in _FIREFOX_PREFS}


def _firefox_block(prefs: dict[str, str], originals: dict[str, str | None]) -> str:
    lines = [_BLOCK_BEGIN, _ORIGINAL_PREFIX + json.dumps(originals)]
    lines += [f'user_pref("{name}", {value});' for name, value in prefs.items()]
    lines.append(_BLOCK_END)
    return "\n".join(lines)


def _join(rest: str, block: str) -> str:
    rest = rest.rstrip("\n")
    return (rest + "\n" if rest else "") + block + "\n"


def _read_prefs(text: str) -> dict[str, str]:
    prefs: dict[str, str] = {}
    for line in text.splitlines():
        match = _PREF_RE.match(line)
        if match:
            prefs[match.group(1)] = match.group(2)
    return prefs


def _set_prefs(text: str, values: dict[str, str | None]) -> str:
    """Troca/remove as prefs gerenciadas no prefs.js (None = volta ao padrão do Firefox)."""
    kept = [line for line in text.splitlines()
            if not ((m := _PREF_RE.match(line)) and m.group(1) in values)]
    kept += [f'user_pref("{name}", {value});' for name, value in values.items() if value is not None]
    return "\n".join(kept) + "\n"


# ---------------------------------------------------------------------------
# Chrome/Chromium e derivados
# ---------------------------------------------------------------------------

_CHROMIUM_DESKTOP_FILES = (
    "google-chrome.desktop", "google-chrome-beta.desktop", "google-chrome-unstable.desktop",
    "com.google.Chrome.desktop", "com.google.ChromeDev.desktop",
    "chromium.desktop", "chromium-browser.desktop", "org.chromium.Chromium.desktop",
    "chromium_chromium.desktop", "io.github.ungoogled_software.ungoogled_chromium.desktop",
    "microsoft-edge.desktop", "microsoft-edge-beta.desktop", "microsoft-edge-dev.desktop",
    "com.microsoft.Edge.desktop",
    "brave-browser.desktop", "brave-browser-beta.desktop", "brave-browser-nightly.desktop",
    "com.brave.Browser.desktop", "brave_brave.desktop",
    "vivaldi-stable.desktop", "vivaldi-snapshot.desktop", "com.vivaldi.Vivaldi.desktop",
    "opera.desktop", "com.opera.Opera.desktop", "opera_opera.desktop",
)
_EXTRA_APP_DIRS = (Path("/var/lib/flatpak/exports/share/applications"),
                   Path("/var/lib/snapd/desktop/applications"))
_OVERRIDE_MARK = "X-Proxy-Manager-Override=true"
# Primeiro código de campo (%U, %u, %F, %f) ou marcador de repasse de arquivos do Flatpak (@@u, @@):
# a flag entra antes dele, junto dos argumentos do navegador.
_FIELD_CODE_RE = re.compile(r"\s(?:%[uUfF]|@@u?)(?=\s|$)")


def _user_apps_dir() -> Path:
    return si._desktop_home() / ".local" / "share" / "applications"


def _system_app_dirs() -> list[Path]:
    home = si._desktop_home()
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [home / ".local/share/flatpak/exports/share/applications",
            *(Path(d) / "applications" for d in data_dirs.split(":") if d),
            *_EXTRA_APP_DIRS]
    user_dir = _user_apps_dir()
    return [d for d in dict.fromkeys(dirs) if d != user_dir]


def with_pac_flag(desktop_entry: str, url: str) -> str:
    flag = f"--proxy-pac-url={url}"
    out: list[str] = []
    for line in desktop_entry.splitlines():
        if line.startswith("Exec="):
            match = _FIELD_CODE_RE.search(line)
            line = f"{line[:match.start()]} {flag}{line[match.start():]}" if match else f"{line} {flag}"
        elif line.startswith("DBusActivatable="):
            line = "DBusActivatable=false"  # senão o menu ignora o Exec= e a flag
        out.append(line)
        if line.strip() == "[Desktop Entry]":
            out.append(_OVERRIDE_MARK)
    return "\n".join(out) + "\n"


def _entry_name(desktop_entry: str) -> str | None:
    return next((line[5:].strip() for line in desktop_entry.splitlines() if line.startswith("Name=")), None)


# Nomes dos processos dos navegadores acima (nativos, Flatpak e Snap rodam com esses nomes).
_CHROMIUM_PROCESSES = frozenset({"chrome", "chromium", "chromium-browser", "msedge", "brave",
                                 "vivaldi-bin", "opera"})


def _chromium_running() -> bool:
    """O GNOME/KDE ligam cada janela aberta ao .desktop do app. Apagar ou trocar esse arquivo com o
    navegador aberto faz o painel refazer a ligação, e as janelas somem como se tivessem sido
    minimizadas/fechadas. Por isso só mexemos nos atalhos com os navegadores fechados."""
    try:
        import psutil
        return any((proc.info.get("name") or "").lower() in _CHROMIUM_PROCESSES
                   for proc in psutil.process_iter(["name"]))
    except Exception:
        return False


def _refresh_desktop_database() -> None:
    if not si._has_binary("update-desktop-database"):
        return
    try:
        si._run_as_desktop_user(["update-desktop-database", str(_user_apps_dir())])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@dataclass
class BrowserResult:
    firefox_profiles: int = 0
    chromium: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def configured_any(self) -> bool:
        return bool(self.firefox_profiles or self.chromium)


def apply(url: str) -> BrowserResult:
    result = BrowserResult()

    for profile in firefox_profiles():
        try:
            apply_firefox(profile, url)
            result.firefox_profiles += 1
        except _ERRORS as exc:
            result.messages.append(f"Firefox ({profile}): falhou: {si._cmd_error(exc)}")
    if result.firefox_profiles:
        result.messages.append(
            f"Firefox: {result.firefox_profiles} perfil(is) configurado(s) — feche e abra o Firefox para valer.")

    user_dir = _user_apps_dir()
    system_dirs = _system_app_dirs()
    changed = False
    for name in _CHROMIUM_DESKTOP_FILES:
        source = next((d / name for d in system_dirs if (d / name).is_file()), None)
        if source is None:
            continue
        target = user_dir / name
        try:
            existing = si._read_user_file(target)
            if existing and _OVERRIDE_MARK not in existing:
                result.messages.append(
                    f"{target} é um atalho seu — não mexi; adicione --proxy-pac-url={url} na linha Exec= dele.")
                continue
            entry = si._read_user_file(source)
            wanted = with_pac_flag(entry, url)
            # Só grava se mudou (1ª vez ou troca da porta do PAC): regravar a cada motor ligado
            # faria o painel do GNOME/KDE refazer a ligação das janelas abertas (veja
            # _chromium_running).
            if existing != wanted:
                si._write_user_file(target, wanted)
                changed = True
            result.chromium.append(_entry_name(entry) or name)
        except _ERRORS as exc:
            result.messages.append(f"{name}: falhou: {si._cmd_error(exc)}")
    if changed:
        _refresh_desktop_database()
    if result.chromium:
        result.messages.append(
            f"{', '.join(result.chromium)}: atalho do menu ajustado com --proxy-pac-url — feche TODAS as "
            f"janelas (e o ícone da bandeja, se houver) e abra de novo pelo menu.")
    return result


def remove(keep_launchers: bool = False) -> list[str]:
    """keep_launchers=True (motor parando): o Firefox é restaurado, mas os atalhos do Chromium
    ficam — sem o motor o PAC não responde e o navegador conecta direto, e não mexer neles evita
    que as janelas abertas sumam da tela. Eles só saem ao desativar a integração."""
    messages: list[str] = []
    restored = 0
    for profile in firefox_profiles():
        try:
            restored += remove_firefox(profile)
        except _ERRORS as exc:
            messages.append(f"Firefox ({profile}): falhou ao restaurar: {si._cmd_error(exc)}")
    if restored:
        messages.append(f"Firefox: proxy restaurado em {restored} perfil(is).")

    if keep_launchers:
        return messages

    removed: list[str] = []
    user_dir = _user_apps_dir()
    overrides: list[tuple[Path, str]] = []
    for name in _CHROMIUM_DESKTOP_FILES:
        target = user_dir / name
        try:
            entry = si._read_user_file(target)
        except _ERRORS as exc:
            messages.append(f"{name}: falhou ao restaurar: {si._cmd_error(exc)}")
            continue
        if _OVERRIDE_MARK in entry:
            overrides.append((target, entry))
    if overrides and _chromium_running():
        # Fica para a próxima remoção com o navegador fechado. Enquanto isso o atalho ainda aponta
        # para o PAC, que sem o motor não responde — e aí o navegador conecta direto.
        messages.append("Navegador aberto: o atalho ajustado do menu será restaurado quando você "
                        "fechá-lo e remover a integração de novo (sem o motor, ele conecta direto).")
        overrides = []
    for target, entry in overrides:
        try:
            si._delete_user_file(target)
            removed.append(_entry_name(entry) or target.name)
        except _ERRORS as exc:
            messages.append(f"{target.name}: falhou ao restaurar: {si._cmd_error(exc)}")
    if removed:
        _refresh_desktop_database()
        messages.append(f"{', '.join(removed)}: atalho original do menu restaurado.")
    return messages
