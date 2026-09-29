# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller — compartilhada entre Windows e Linux (roda no SO em que for invocada;
PyInstaller não faz cross-compile).

Por padrão o executável roda como usuário comum (basta para o modo explícito/PAC). Com
PROXY_MANAGER_ADMIN=1 (scripts/build_windows.ps1 -Admin), no Windows embute um manifesto pedindo
elevação (UAC) ao abrir — necessário só para o modo transparente. No Linux não existe esse
mecanismo: a elevação lá é feita por fora, via pkexec (scripts/build_linux.sh --admin).

Uso: use scripts/build_windows.ps1 ou scripts/build_linux.sh (geram o ícone e chamam isto).
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 -- SPECPATH é injetado pelo PyInstaller
ICON_ICO = str(ROOT / "packaging" / "icon.ico")
ICON_PNG = str(ROOT / "packaging" / "icon.png")
IS_WINDOWS = sys.platform == "win32"
REQUIRE_ADMIN = os.environ.get("PROXY_MANAGER_ADMIN") == "1"

# keyring descobre seus backends via entry points (pkg_resources) — mecanismo que o PyInstaller
# não segue sozinho por análise estática. Sem isso, o app funcionaria no dev normalmente e falhar
# silenciosamente ao salvar/ler senhas só no executável empacotado.
HIDDEN_IMPORTS = [
    "keyring.backends.Windows",
    "keyring.backends.SecretService",
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",
    "keyring.backends.macOS",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ProxyManager" if IS_WINDOWS else "proxy-manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # app gráfico: sem janela de console atrás
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_ICO if IS_WINDOWS else ICON_PNG,
    uac_admin=IS_WINDOWS and REQUIRE_ADMIN,  # pede UAC ao abrir (só com -Admin)
)
