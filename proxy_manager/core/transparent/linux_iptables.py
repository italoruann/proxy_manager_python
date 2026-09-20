"""Esboço do modo transparente no Linux (Fase 2 — não implementado nesta versão).

Ideia de implementação futura (estilo redsocks):
1. Criar uma cadeia iptables/nftables própria na tabela `nat`, com regras `REDIRECT` que
   desviam conexões TCP saintes (exceto as originadas pelo próprio Proxy Manager, para evitar
   loop) para uma porta local onde o `ProxyEngine` escuta em modo transparente.
2. No handler da conexão redirecionada, obter o destino original via `getsockopt(SO_ORIGINAL_DST)`
   (constante 80 no Linux), já que o socket aceito aponta para a porta local, não para o destino real.
3. Identificar o processo de origem via `/proc/net/tcp` + `/proc/<pid>/fd` (ou reaproveitar
   `psutil.net_connections`, como já fazemos no modo explícito) e aplicar o mesmo `RuleSet`.
4. Exigir privilégio de root para manipular iptables/nftables; expor start/stop que apliquem e
   revertam as regras de forma limpa (nunca deixar o sistema sem rota em caso de crash).

Requer execução como root e é potencialmente disruptivo para a conectividade se mal configurado
— por isso fica isolado deste módulo e desligado por padrão.
"""
from __future__ import annotations


class LinuxTransparentMode:
    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "Modo transparente no Linux ainda não foi implementado. "
            "Use o modo explícito (proxy local + integração via PAC)."
        )
