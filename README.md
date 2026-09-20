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
> modo explícito acima. Para esses casos existe o **modo transparente** (aba Configurações):
> interceptação em nível de sistema, via `iptables` (Linux) ou o driver WinDivert/`pydivert`
> (Windows), redirecionando qualquer conexão TCP de saída pro Proxy Manager sem o app precisar
> cooperar. Exige rodar como root/administrador. Cobre só TCP/IPv4 — QUIC/HTTP3 (UDP) ainda
> passa direto. Regras por domínio continuam funcionando nesse modo por meio de uma espiada
> passiva no SNI (HTTPS) ou no cabeçalho Host (HTTP); veja `proxy_manager/core/transparent/`.

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

## Executável empacotado (abre já elevado)

Pra não precisar de terminal elevado nem configurar "Executar como administrador" toda vez,
dá pra gerar um executável standalone (não precisa de Python instalado na máquina de destino)
que já pede elevação sozinho ao abrir:

```bash
pip install -r requirements-build.txt
```

**Windows** (`scripts/build_windows.ps1`): gera `dist\ProxyManager.exe` com um manifesto UAC
embutido (`uac_admin`) — todo clique nele já pede elevação, sem passo manual nenhum. O
início automático (aba Configurações) usa uma Tarefa Agendada com `/RL HIGHEST`, não a chave
`Run` do registro — itens do `Run` sobem sem privilégio nenhum no login e nunca conseguiriam
abrir um executável que exige admin.

**Linux** (`scripts/build_linux.sh`, rodar em Linux — PyInstaller não faz cross-compile): gera
`dist/proxy-manager`. Diferente do Windows, um executável Linux não tem como se auto-elevar
sozinho ao ser aberto — e colocar bit SUID nele seria uma vulnerabilidade conhecida (um binário
PyInstaller extrai bibliotecas pra um diretório temporário em tempo de execução, o que abre
brecha de escalonamento de privilégio). Em vez disso, `sudo packaging/linux/install.sh` instala
em `/opt/proxy-manager` e registra um atalho que abre via `pkexec` — pede a senha graficamente,
sem terminal nem sudo, exatamente como o UAC do Windows. `packaging/linux/proxy-manager.sh`
faz a mesma coisa por linha de comando.

## Testes

```bash
pytest tests/
```

Inclui testes de unidade do motor de regras, testes de integração do engine (SOCKS5/HTTP reais
em loopback) e um smoke test da interface gráfica (offscreen, sem precisar de tela).

## Limitações conhecidas / roadmap

- Modo transparente cobre só TCP/IPv4. Sem suporte a UDP — QUIC/HTTP3 (usado por padrão pelo
  Chrome em vários sites Google e CDNs) não é interceptado nem no modo transparente nem no
  explícito; desative QUIC no navegador (`chrome://flags/#enable-quic`) se isso for um problema.
- No modo transparente, a tradução de pacotes do Windows (WinDivert/`pydivert`) foi implementada
  seguindo a técnica padrão de NAT em espaço de usuário, mas só pode ser validada de fato rodando
  como Administrador numa máquina real — teste com cautela antes de depender dela no dia a dia.
- O empacotamento Windows (`ProxyManager.exe` com UAC embutido) foi gerado e verificado nesta
  máquina — o manifesto `requireAdministrator` está de fato no binário. O empacotamento Linux
  (`scripts/build_linux.sh`, `packaging/linux/`) não foi testado numa máquina Linux real; o
  fluxo via `pkexec` segue a prática padrão do PolicyKit, mas confirme antes de depender dele.
- SOCKS5 (modo explícito) só resolve por domínio se o próprio app enviar o hostname (remote DNS);
  caso contrário, o motor só enxerga o IP de destino (regras CIDR/IP ainda funcionam normalmente).
- Sem UDP ASSOCIATE no modo explícito (só TCP/CONNECT), cobre a grande maioria dos usos.
- Firefox não segue automaticamente as configurações de proxy do Windows/GNOME por padrão em
  todas as instalações — pode ser necessário colar a URL do PAC manualmente em
  Configurações → Rede.
