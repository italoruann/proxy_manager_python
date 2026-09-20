#!/bin/sh
# Gera dist/proxy-manager: standalone (nao precisa de Python instalado na maquina de destino).
# Rode isto EM Linux -- PyInstaller nao faz cross-compile a partir do Windows/macOS.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
fi

echo "Gerando icone..."
"$PYTHON" packaging/generate_icon.py

echo ""
echo "Rodando PyInstaller..."
"$PYTHON" -m PyInstaller packaging/proxy_manager.spec --noconfirm --distpath dist --workpath build

echo ""
echo "Executavel gerado em dist/proxy-manager"
echo "Rode sudo packaging/linux/install.sh pra instalar e registrar o atalho que pede elevacao"
echo "via pkexec (a senha e pedida graficamente ao abrir -- nao precisa de terminal nem sudo)."
