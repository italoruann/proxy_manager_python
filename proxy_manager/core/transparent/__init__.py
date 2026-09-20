"""Modo transparente (Fase 2, futura): interceptação de tráfego no nível de sistema,
sem exigir que o app aponte para o proxy explicitamente.

- Linux: redirecionamento via iptables/nftables + SO_ORIGINAL_DST (estilo redsocks).
- Windows: captura de pacotes via WinDivert (driver assinado) + tabela de conexões do SO.

Ainda não implementado nesta versão — ver `linux_iptables.py` e `windows_windivert.py`.
"""
