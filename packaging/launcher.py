"""Ponto de entrada usado pelo executável empacotado (PyInstaller) — só repassa pra main() de
verdade; existe como arquivo separado porque o PyInstaller trabalha melhor com um script simples
do que com `python -m pacote`."""
from proxy_manager.main import main

if __name__ == "__main__":
    main()
