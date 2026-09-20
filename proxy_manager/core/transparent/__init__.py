"""Modo transparente: interceptação de tráfego no nível de sistema, sem exigir que o app aponte
para o proxy explicitamente. Exige root/administrador; liga e desliga junto com o motor.

- Linux: redirecionamento via nftables + SO_ORIGINAL_DST (estilo redsocks) — ver `linux_nftables.py`.
- Windows: captura de pacotes via WinDivert (driver assinado) + NAT em espaço de usuário — ver
  `windows_windivert.py`.

Cobre só IPv4/TCP nos dois; sem suporte a UDP (QUIC/HTTP3 continua indo direto).
"""
