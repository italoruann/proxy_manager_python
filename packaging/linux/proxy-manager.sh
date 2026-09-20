#!/bin/sh
# Abre o Proxy Manager já elevado, via pkexec (PolicyKit) -- pede a senha graficamente, sem
# precisar de sudo nem terminal. É o equivalente, no Linux, ao UAC do Windows.
#
# O binário em si NUNCA fica com bit SUID: SUID num executável PyInstaller é uma vulnerabilidade
# de escalonamento de privilégio conhecida (ele extrai bibliotecas para um diretório temporário
# em tempo de execução, mundo-gravável) -- pkexec entrega a mesma experiência sem esse risco.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$DIR/proxy-manager"
if [ ! -x "$BIN" ]; then
    BIN="/opt/proxy-manager/proxy-manager"
fi

if [ ! -x "$BIN" ]; then
    echo "Não encontrei o executável do Proxy Manager (procurei em $DIR e /opt/proxy-manager)." >&2
    echo "Rode scripts/build_linux.sh e/ou packaging/linux/install.sh primeiro." >&2
    exit 1
fi

exec pkexec "$BIN" "$@"
