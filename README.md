# Proxy Manager

Um gerenciador de proxy multiplataforma (Windows e Linux), inspirado no Proxifier, com regras
avançadas por aplicativo e por domínio, múltiplos perfis de proxy (SOCKS5/HTTP) e um log de
conexões em tempo real para você confirmar que o proxy está realmente sendo usado.

## Como funciona (modo explícito)

1. O programa sobe dois servidores locais em `127.0.0.1`: um **SOCKS5** e um **HTTP** (com
   suporte a `CONNECT` para HTTPS).
2. Ele pode configurar automaticamente o proxy do sistema operacional para usar um arquivo
   **PAC** servido localmente, fazendo com que navegadores e a maioria dos programas passem a
   rotear o tráfego pelos listeners acima — sem precisar configurar cada aplicativo manualmente.
3. Toda conexão que chega é identificada (processo de origem, domínio/IP de destino) e passa
   pelo motor de regras, que decide: ir **direto**, ir **via um proxy** específico, ou ser
   **bloqueada**.
4. Cada decisão fica visível, em tempo real, na página **Logs**.

> Apps que ignoram completamente as configurações de proxy do sistema não são capturados no
> modo explícito. Um modo transparente (interceptação em nível de sistema via iptables no Linux
> e WinDivert no Windows) está esboçado em `proxy_manager/core/transparent/` para uma fase
> futura, mas ainda não implementado.

## Regras

Arquivo de regras (editável tanto em tabela quanto em texto na aba **Regras**):

```
apps: chrome.exe, msedge.exe      # escopo por app (opcional; "apps: *" volta a valer para todos)
*.azure.com
*.digitalocean.com

apps: *
*.paypal.com +direct
*.stripe.com +direct

*.interno.corp +proxy:vpn-escritorio
ads.tracker.com +block
```

- Regras são avaliadas de cima para baixo; a primeira que casar (aplicativo **e** destino) vence.
- Sem sufixo: usa o proxy padrão. `+direct`: vai direto. `+block`: bloqueia. `+proxy:nome`: usa
  um perfil de proxy específico.
- Alvos aceitam `*.dominio.com`, IP exato ou CIDR (`10.0.0.0/8`).
- Prefixe uma linha com `!` para desabilitá-la sem apagar.

## Instalação e execução

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m proxy_manager
```

## Testes

```bash
pytest tests/
```

Inclui testes de unidade do motor de regras, testes de integração do engine (SOCKS5/HTTP reais
em loopback) e um smoke test da interface gráfica (offscreen, sem precisar de tela).

## Limitações conhecidas / roadmap

- Modo transparente (captura de qualquer app sem configurar proxy do sistema) ainda não
  implementado — ver `proxy_manager/core/transparent/`.
- SOCKS5 só resolve por domínio se o próprio app enviar o hostname (remote DNS); caso contrário,
  o motor só enxerga o IP de destino (regras CIDR/IP ainda funcionam normalmente).
- Sem UDP ASSOCIATE (só TCP/CONNECT), cobre a grande maioria dos usos.
- Firefox não segue automaticamente as configurações de proxy do Windows/GNOME por padrão em
  todas as instalações — pode ser necessário colar a URL do PAC manualmente em
  Configurações → Rede.
