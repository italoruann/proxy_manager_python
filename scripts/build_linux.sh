#!/bin/sh
# Gera dist/proxy-manager: standalone (nao precisa de Python instalado na maquina de destino).
# Rode isto EM Linux -- PyInstaller nao faz cross-compile a partir do Windows/macOS.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv nao encontrado -- instale em https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

# Garante o .venv com as dependencias do app + grupo "build" (PyInstaller) travadas no uv.lock.
uv sync --locked --group build

echo "Gerando icone..."
uv run --no-sync python packaging/generate_icon.py

echo ""
echo "Rodando PyInstaller..."
uv run --no-sync python -m PyInstaller packaging/proxy_manager.spec --noconfirm --distpath dist --workpath build

echo ""
echo "Executavel gerado em dist/proxy-manager"
echo "Rode sudo packaging/linux/install.sh pra instalar e registrar o atalho que pede elevacao"
echo "via pkexec (a senha e pedida graficamente ao abrir -- nao precisa de terminal nem sudo)."
