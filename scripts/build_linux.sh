#!/bin/sh
# Gera dist/proxy-manager: standalone (nao precisa de Python instalado na maquina de destino).
# Rode isto EM Linux -- PyInstaller nao faz cross-compile a partir do Windows/macOS.
#
#   ./scripts/build_linux.sh                    so gera dist/proxy-manager
#   ./scripts/build_linux.sh --install          gera e instala pro seu usuario (~/.local), sem sudo,
#                                               com atalho no menu -- roda como usuario comum
#   ./scripts/build_linux.sh --install --admin  gera e instala em /opt (pede sudo) com atalho que
#                                               abre via pkexec -- necessario so pro modo transparente
#   ./scripts/build_linux.sh --uninstall        fecha o app e remove todas as instalacoes
#
# Sempre fecha o Proxy Manager se estiver aberto e apaga o build anterior. Com --install, remove
# antes qualquer instalacao anterior (de usuario e de admin), pra nunca ficarem duas no menu.
#
# Usa o uv se estiver instalado; senao cria/usa o .venv com o pip.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

INSTALL=0
ADMIN=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --install) INSTALL=1 ;;
        --admin) ADMIN=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) echo "Opcao desconhecida: $arg (use --help)" >&2; exit 1 ;;
    esac
done

USER_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/proxy-manager"
USER_DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/proxy-manager.desktop"
ADMIN_DIR=/opt/proxy-manager
ADMIN_DESKTOP=/usr/share/applications/proxy-manager.desktop
AUTOSTART="$HOME/.config/autostart/proxy-manager.desktop"

# --- Ambiente Python ------------------------------------------------------------

setup_python() {
    # O instalador do uv poe ele em ~/.local/bin, que nem sempre esta no PATH do terminal atual.
    UV="$(command -v uv || true)"
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        [ -z "$UV" ] && [ -x "$candidate" ] && UV="$candidate"
    done

    if [ -n "$UV" ]; then
        # Dependencias do app + grupo "build" (PyInstaller), travadas no uv.lock.
        "$UV" sync --locked --group build
        run_python() { "$UV" run --no-sync python "$@"; }
    else
        if [ ! -x .venv/bin/python ]; then
            echo "Criando .venv..."
            PY="$(command -v python3.14 || command -v python3 || true)"
            [ -n "$PY" ] || { echo "Python 3.14+ nao encontrado." >&2; exit 1; }
            "$PY" -m venv .venv
        fi
        # Um .venv criado pelo uv nao traz o pip.
        .venv/bin/python -m pip --version >/dev/null 2>&1 || .venv/bin/python -m ensurepip --upgrade
        .venv/bin/python -m pip install --quiet -e . "pyinstaller>=6.16"
        run_python() { .venv/bin/python "$@"; }
    fi
}

# --- Remocao da versao anterior -------------------------------------------------

is_running() { pgrep -x proxy-manager >/dev/null 2>&1; }

# Fecha o app com SIGTERM, que ele trata saindo pelo caminho normal (para o motor e desfaz o proxy
# dos navegadores). So mata a forca se nao sair em 10s -- e ai desfaz o proxy por aqui.
stop_running() {
    is_running || return 0
    echo "Fechando o Proxy Manager em execucao..."
    SUDO=""
    if pgrep -x -u root proxy-manager >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
        SUDO="sudo"  # instalacao de admin (pkexec) roda como root
    fi
    $SUDO pkill -TERM -x proxy-manager 2>/dev/null || true
    i=0
    while is_running && [ "$i" -lt 20 ]; do
        sleep 0.5
        i=$((i + 1))
    done
    if is_running; then
        $SUDO pkill -KILL -x proxy-manager 2>/dev/null || true
        sleep 1
        echo "Desfazendo o proxy dos navegadores/sistema..."
        run_python -c "from proxy_manager.core.system_integration import remove_system_proxy; print(remove_system_proxy(keep_browser_launchers=True)[1])" || true
    fi
}

uninstall_all() {
    if [ -e "$USER_DIR" ] || [ -e "$USER_DESKTOP" ]; then
        echo "Removendo a instalacao anterior em $USER_DIR..."
        rm -rf "$USER_DIR"
        rm -f "$USER_DESKTOP"
    fi
    if [ -e "$ADMIN_DIR" ] || [ -e "$ADMIN_DESKTOP" ]; then
        echo "Removendo a instalacao anterior em $ADMIN_DIR (pede sudo)..."
        sudo rm -rf "$ADMIN_DIR" "$ADMIN_DESKTOP"
    fi
}

setup_python
stop_running

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_all
    # O inicio automatico apontava para o executavel instalado, que nao existe mais.
    if [ -f "$AUTOSTART" ] && grep -qE "$USER_DIR|$ADMIN_DIR" "$AUTOSTART"; then
        rm -f "$AUTOSTART"
    fi
    echo "Proxy Manager desinstalado."
    exit 0
fi

echo "Removendo o build anterior..."
rm -rf build dist/proxy-manager

# --- Build ----------------------------------------------------------------------

echo "Gerando icone..."
run_python packaging/generate_icon.py

echo ""
echo "Rodando PyInstaller..."
run_python -m PyInstaller packaging/proxy_manager.spec --noconfirm --distpath dist --workpath build

echo ""
echo "Executavel gerado em dist/proxy-manager"

if [ "$INSTALL" -eq 0 ]; then
    echo "Para instalar com atalho no menu: ./scripts/build_linux.sh --install"
    exit 0
fi

# --- Instalacao -----------------------------------------------------------------

uninstall_all

if [ "$ADMIN" -eq 1 ]; then
    # /opt, dono root e sem escrita pra outros: exigido pelo pkexec (o alvo nao pode ser
    # gravavel por quem nao e root).
    sudo packaging/linux/install.sh
    exit 0
fi

mkdir -p "$USER_DIR" "$(dirname "$USER_DESKTOP")"
install -m 755 dist/proxy-manager "$USER_DIR/proxy-manager"
install -m 644 packaging/icon.png "$USER_DIR/icon.png"
cat >"$USER_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Proxy Manager
Comment=Gerenciador de proxy com regras por aplicativo e domínio
Exec="$USER_DIR/proxy-manager"
Icon=$USER_DIR/icon.png
Terminal=false
Categories=Network;
EOF
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$(dirname "$USER_DESKTOP")" >/dev/null 2>&1 || true

echo "Instalado em $USER_DIR, com atalho 'Proxy Manager' no menu de aplicativos."
