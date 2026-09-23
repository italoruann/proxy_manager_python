#!/bin/sh
# Abre o Proxy Manager elevado no Linux rodando direto com Python (sem precisar empacotar) --
# libera o root pra acessar seu display grafico (Wayland/X11, que ele nao tem por padrao) e abre
# o app via pkexec com o backend X11 do Qt (QT_QPA_PLATFORM=xcb), que o root consegue usar.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "Não encontrei $ROOT/.venv/bin/python -- crie o venv e instale as dependências primeiro:" >&2
    echo "  uv sync" >&2
    exit 1
fi

xhost +SI:localuser:root >/dev/null

exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" QT_QPA_PLATFORM=xcb \
    bash -c "cd '$ROOT' && '$ROOT/.venv/bin/python' -m proxy_manager"
