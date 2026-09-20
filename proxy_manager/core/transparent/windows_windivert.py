"""Esboço do modo transparente no Windows (Fase 2 — não implementado nesta versão).

Ideia de implementação futura:
1. Usar o driver assinado WinDivert (via bindings Python, ex.: `pydivert`) para interceptar
   pacotes TCP SYN em nível de rede, redirecionando a conexão para uma porta local do
   `ProxyEngine` operando em modo transparente (reescrevendo endereço/porta de destino).
2. Recuperar o destino original (guardado em uma tabela de mapeamento porta-efêmera -> destino
   real, preenchida no momento da interceptação do SYN).
3. Identificar o processo de origem via `GetExtendedTcpTable` (já coberto de forma equivalente
   pelo `psutil.net_connections` usado no modo explícito) e aplicar o mesmo `RuleSet`.
4. Exigir privilégio de administrador para instalar/usar o driver WinDivert.

Requer executar como administrador e instalar o driver WinDivert — por isso fica isolado deste
módulo e desligado por padrão.
"""
from __future__ import annotations


class WindowsTransparentMode:
    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "Modo transparente no Windows ainda não foi implementado. "
            "Use o modo explícito (proxy local + integração via PAC)."
        )
