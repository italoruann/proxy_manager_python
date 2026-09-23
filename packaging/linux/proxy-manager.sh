#!/bin/sh
# Abre o Proxy Manager já elevado, via pkexec (PolicyKit) -- pede a senha graficamente, sem
# precisar de sudo nem terminal. É o equivalente, no Linux, ao UAC do Windows.
#
# O binário em si NUNCA fica com bit SUID: SUID num executável PyInstaller é uma vulnerabilidade
# de escalonamento de privilégio conhecida (ele extrai bibliotecas para um diretório temporário
# em tempo de execução, mundo-gravável) -- pkexec entrega a mesma experiência sem esse risco.
#
# pkexec apaga o ambiente (DISPLAY, XAUTHORITY, WAYLAND_DISPLAY...) e o root não tem permissão
# no display do usuário por padrão. Chamar `pkexec proxy-manager` direto faz o Qt não achar
# nenhuma tela e o processo morrer em silêncio logo depois da senha. Por isso: libera o root no
# display via xhost, repassa DISPLAY/XAUTHORITY e força o backend X11 do Qt (xcb), que funciona
# também em sessões Wayland através do XWayland.

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/proxy-manager"
if [ ! -x "$BIN" ]; then
    BIN="/opt/proxy-manager/proxy-manager"
fi

LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/proxy-manager"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/launcher.log"

# Aberto pelo menu não há terminal pra mostrar erro: vai pro log e, se der, vira notificação.
fail() {
    echo "$(date '+%F %T') $1" >>"$LOG"
    echo "$1" >&2
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -i dialog-error "Proxy Manager" "$1"
    fi
    exit 1
}

if [ ! -x "$BIN" ]; then
    fail "Não encontrei o executável do Proxy Manager (procurei em $DIR e /opt/proxy-manager). Rode scripts/build_linux.sh e/ou packaging/linux/install.sh primeiro."
fi

if [ -z "$DISPLAY" ]; then
    fail "Nenhum display X11/XWayland disponível (DISPLAY vazio) -- o root não consegue abrir a janela."
fi

if ! command -v xhost >/dev/null 2>&1; then
    fail "Comando 'xhost' não encontrado. Instale-o (Fedora: sudo dnf install xhost; Debian/Ubuntu: sudo apt install x11-xserver-utils)."
fi

xhost +SI:localuser:root >/dev/null

echo "$(date '+%F %T') iniciando $BIN" >>"$LOG"
pkexec env DISPLAY="$DISPLAY" XAUTHORITY="${XAUTHORITY:-}" QT_QPA_PLATFORM=xcb \
    "$BIN" "$@" >>"$LOG" 2>&1
status=$?

# Revoga o acesso do root ao display assim que o app fecha.
xhost -SI:localuser:root >/dev/null 2>&1

case "$status" in
    0) ;;
    126|127) echo "$(date '+%F %T') autenticação cancelada ou negada (pkexec saiu com $status)" >>"$LOG" ;;
    *) fail "O Proxy Manager fechou com erro (código $status). Detalhes em $LOG" ;;
esac
exit "$status"
