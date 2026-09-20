# -*- mode: python ; coding: utf-8 -*-
"""Spec do PyInstaller — compartilhada entre Windows e Linux (roda no SO em que for invocada;
PyInstaller não faz cross-compile). No Windows, embute um manifesto pedindo elevação (UAC)
sempre que o executável for aberto, direto; no Linux não existe esse mecanismo — a elevação lá é
feita por fora, via pkexec (veja packaging/linux/).

Uso: pyinstaller packaging/proxy_manager.spec --noconfirm
(os scripts/build_windows.ps1 e scripts/build_linux.sh já fazem isso, incluindo gerar o ícone.)
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 -- SPECPATH é injetado pelo PyInstaller
ICON_ICO = str(ROOT / "packaging" / "icon.ico")
ICON_PNG = str(ROOT / "packaging" / "icon.png")
IS_WINDOWS = sys.platform == "win32"

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
    uac_admin=IS_WINDOWS,  # pede elevação (UAC) sozinho toda vez que o .exe é aberto
)
