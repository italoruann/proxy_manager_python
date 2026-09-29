"""Testes da configuração direta dos navegadores no Linux: tudo numa HOME falsa em tmp_path, sem
subprocess (rodando como o próprio usuário os arquivos são lidos/gravados direto)."""
import pytest

from proxy_manager.core import browser_proxy as bp
from proxy_manager.core import system_integration as si

PAC = "http://127.0.0.1:58093/proxy.pac"

CHROME_ENTRY = """\
[Desktop Entry]
Name=Google Chrome
Exec=/usr/bin/google-chrome-stable %U
Type=Application

[Desktop Action new-private-window]
Name=New Incognito Window
Exec=/usr/bin/google-chrome-stable --incognito
"""

FLATPAK_BRAVE_ENTRY = """\
[Desktop Entry]
Name=Brave
Exec=/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=brave --file-forwarding com.brave.Browser @@u %U @@
DBusActivatable=true
"""


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(si, "_desktop_uid", lambda: None)
    monkeypatch.setattr(si, "_desktop_home", lambda: home)
    monkeypatch.setattr(si, "_has_binary", lambda name: False)
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "usr-share"))
    monkeypatch.setattr(bp, "_EXTRA_APP_DIRS", (tmp_path / "flatpak-apps",))
    monkeypatch.setattr(bp, "_chromium_running", lambda: False)
    return home


def _profile(home, root=".mozilla/firefox", name="abc.default-release", prefs=""):
    profile = home / root / name
    profile.mkdir(parents=True)
    (profile / "prefs.js").write_text(prefs, encoding="utf-8")
    return profile


def _prefs(profile):
    return bp._read_prefs((profile / "prefs.js").read_text(encoding="utf-8"))


def test_firefox_profiles_found_in_native_flatpak_and_snap(home):
    native = _profile(home)
    flatpak = _profile(home, ".var/app/org.mozilla.firefox/.mozilla/firefox")
    snap = _profile(home, "snap/firefox/common/.mozilla/firefox")
    (home / ".mozilla/firefox/Crash Reports").mkdir()
    assert bp.firefox_profiles() == [native, flatpak, snap]


def test_firefox_apply_writes_user_js_and_remove_restores_original(home):
    profile = _profile(home, prefs='user_pref("network.proxy.type", 1);\nuser_pref("browser.x", true);\n')
    (profile / "user.js").write_text('user_pref("minha.pref", 1);\n', encoding="utf-8")

    result = bp.apply(PAC)
    assert result.firefox_profiles == 1
    user_js = (profile / "user.js").read_text(encoding="utf-8")
    assert user_js.startswith('user_pref("minha.pref", 1);\n')
    assert bp._read_prefs(user_js) == {
        "minha.pref": "1", "network.proxy.type": "2", "network.proxy.autoconfig_url": f'"{PAC}"'}

    # O Firefox grava no prefs.js o que leu do user.js; a remoção precisa desfazer isso.
    (profile / "prefs.js").write_text(
        f'user_pref("browser.x", true);\nuser_pref("network.proxy.type", 2);\n'
        f'user_pref("network.proxy.autoconfig_url", "{PAC}");\n', encoding="utf-8")
    bp.apply(PAC)  # reaplicar não pode perder o original
    bp.remove()

    assert (profile / "user.js").read_text(encoding="utf-8") == 'user_pref("minha.pref", 1);\n'
    assert _prefs(profile) == {"browser.x": "true", "network.proxy.type": "1"}


def test_firefox_remove_deletes_user_js_we_created(home):
    profile = _profile(home)
    bp.apply(PAC)
    bp.remove()
    assert not (profile / "user.js").exists()
    assert _prefs(profile) == {}


def test_firefox_running_keeps_restore_block_until_closed(home):
    profile = _profile(home)
    bp.apply(PAC)
    (profile / "lock").write_text("", encoding="utf-8")
    bp.remove()
    restore = bp._read_prefs((profile / "user.js").read_text(encoding="utf-8"))
    assert restore == {"network.proxy.type": "5", "network.proxy.autoconfig_url": '""'}

    (profile / "lock").unlink()
    bp.remove()
    assert not (profile / "user.js").exists()


def test_chromium_launchers_get_pac_flag_and_are_removed(home, tmp_path):
    (tmp_path / "usr-share/applications").mkdir(parents=True)
    (tmp_path / "usr-share/applications/google-chrome.desktop").write_text(CHROME_ENTRY, encoding="utf-8")
    (tmp_path / "flatpak-apps").mkdir()
    (tmp_path / "flatpak-apps/com.brave.Browser.desktop").write_text(FLATPAK_BRAVE_ENTRY, encoding="utf-8")

    result = bp.apply(PAC)
    assert result.chromium == ["Google Chrome", "Brave"]
    apps = home / ".local/share/applications"
    chrome = (apps / "google-chrome.desktop").read_text(encoding="utf-8")
    assert f"Exec=/usr/bin/google-chrome-stable --proxy-pac-url={PAC} %U" in chrome
    assert f"Exec=/usr/bin/google-chrome-stable --incognito --proxy-pac-url={PAC}" in chrome
    brave = (apps / "com.brave.Browser.desktop").read_text(encoding="utf-8")
    assert f"com.brave.Browser --proxy-pac-url={PAC} @@u %U @@" in brave
    assert "DBusActivatable=false" in brave

    bp.apply(PAC)  # reaplicar não duplica a flag
    assert (apps / "google-chrome.desktop").read_text(encoding="utf-8").count("--proxy-pac-url") == 2

    bp.remove()
    assert not (apps / "google-chrome.desktop").exists()
    assert not (apps / "com.brave.Browser.desktop").exists()


def test_chromium_user_launcher_is_never_overwritten(home, tmp_path):
    (tmp_path / "usr-share/applications").mkdir(parents=True)
    (tmp_path / "usr-share/applications/chromium.desktop").write_text(CHROME_ENTRY, encoding="utf-8")
    mine = home / ".local/share/applications/chromium.desktop"
    mine.parent.mkdir(parents=True)
    mine.write_text("[Desktop Entry]\nExec=meu-chromium\n", encoding="utf-8")

    result = bp.apply(PAC)
    assert result.chromium == []
    assert any("não mexi" in m for m in result.messages)
    bp.remove()
    assert mine.read_text(encoding="utf-8") == "[Desktop Entry]\nExec=meu-chromium\n"


def _install_chrome(tmp_path):
    (tmp_path / "usr-share/applications").mkdir(parents=True)
    (tmp_path / "usr-share/applications/google-chrome.desktop").write_text(CHROME_ENTRY, encoding="utf-8")


def test_engine_stop_keeps_chromium_launchers(home, tmp_path):
    """Regressão: apagar o .desktop com o navegador aberto fazia o GNOME/KDE sumir com as janelas
    dele (pareciam minimizadas/fechadas). Parar o motor não mexe mais nos atalhos."""
    _install_chrome(tmp_path)
    bp.apply(PAC)
    bp.remove(keep_launchers=True)
    assert (home / ".local/share/applications/google-chrome.desktop").exists()


def test_apply_does_not_rewrite_unchanged_launcher(home, tmp_path, monkeypatch):
    _install_chrome(tmp_path)
    bp.apply(PAC)
    writes = []
    real_write = si._write_user_file
    monkeypatch.setattr(si, "_write_user_file", lambda p, t: writes.append(p) or real_write(p, t))
    result = bp.apply(PAC)
    assert result.chromium == ["Google Chrome"]
    assert not [p for p in writes if p.suffix == ".desktop"]


def test_disabling_integration_waits_for_browser_to_close(home, tmp_path, monkeypatch):
    _install_chrome(tmp_path)
    bp.apply(PAC)
    target = home / ".local/share/applications/google-chrome.desktop"

    monkeypatch.setattr(bp, "_chromium_running", lambda: True)
    messages = bp.remove()
    assert target.exists()
    assert any("Navegador aberto" in m for m in messages)

    monkeypatch.setattr(bp, "_chromium_running", lambda: False)
    bp.remove()
    assert not target.exists()
