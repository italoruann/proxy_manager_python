#!/bin/sh
# Instala o Proxy Manager em /opt/proxy-manager, dono root:root e sem escrita para outros
# usuários (exigido pelo pkexec por padrão: o alvo não pode ser gravável por quem não é root) e
# registra o atalho .desktop que pede elevação ao abrir. Rode com sudo -- ele só copia arquivos;
# o app em si nunca fica sempre rodando como root, só quando você realmente abrir.
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Rode este instalador com sudo:" >&2
    echo "  sudo $0" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BIN="$ROOT/dist/proxy-manager"
if [ ! -x "$BIN" ]; then
    echo "Não encontrei $BIN -- rode scripts/build_linux.sh primeiro (sem sudo)." >&2
    exit 1
fi

INSTALL_DIR=/opt/proxy-manager
mkdir -p "$INSTALL_DIR"
install -o root -g root -m 755 "$BIN" "$INSTALL_DIR/proxy-manager"
install -o root -g root -m 644 "$ROOT/packaging/icon.png" "$INSTALL_DIR/icon.png"
install -o root -g root -m 755 "$ROOT/packaging/linux/proxy-manager.sh" "$INSTALL_DIR/proxy-manager.sh"
install -o root -g root -m 644 "$ROOT/packaging/linux/proxy-manager.desktop" /usr/share/applications/proxy-manager.desktop

echo "Instalado em $INSTALL_DIR."
echo "Abra 'Proxy Manager' no menu de aplicativos do seu ambiente gráfico, ou rode:"
echo "  $INSTALL_DIR/proxy-manager.sh"
echo "Os dois pedem a senha graficamente via pkexec antes de abrir."
