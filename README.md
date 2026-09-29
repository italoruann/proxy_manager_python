# Proxy Manager

Gerenciador de proxy para Windows e Linux, inspirado no Proxifier.

- Regras por **aplicativo** e por **domínio** (direto, via proxy ou bloqueado)
- Vários perfis de proxy **SOCKS5** e **HTTP**
- Log de conexões em tempo real, pra confirmar que o proxy está sendo usado

---

## Passo a passo

### 1. Instale o uv

O projeto usa o [uv](https://docs.astral.sh/uv/) para gerenciar Python e dependências.

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Linux**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Feche e abra o terminal de novo, depois confira com `uv --version`.

### 2. Baixe o projeto

```bash
git clone <url-do-repositorio> proxy_manager_python
cd proxy_manager_python
```

### 3. Instale as dependências

```bash
uv sync
```

Esse comando cria a pasta `.venv` e instala tudo o que está no `uv.lock`. Se você não tiver
o **Python 3.14+**, o uv baixa sozinho, então não precisa instalar o Python antes.

### 4. Abra o programa

```bash
uv run python -m proxy_manager
```

No Linux, se faltarem as bibliotecas de sistema que o Qt precisa (como a `libxcb-cursor`), o app
instala sozinho pelo gerenciador de pacotes da distro (pacman, apt, dnf ou zypper), pedindo a
senha via `sudo` ou `pkexec`. Para desativar, use `PROXY_MANAGER_SKIP_DEPS=1`.

### 5. Configure no app

1. Na aba **Proxies**, cadastre seu proxy (SOCKS5 ou HTTP).
2. Na aba **Regras**, defina o que passa pelo proxy (veja [Regras](#regras)).
3. No **Dashboard**, ligue o motor.
4. Acompanhe as conexões na aba **Logs**.

---

## Regras

As regras podem ser editadas em tabela ou em texto na aba **Regras**:

```
apps: chrome.exe, msedge.exe
*.example.com
*.example.org

apps: *
*.meubanco.com.br +direct
*.interno.corp +proxy:trabalho
ads.tracker.com +block
```

| Sintaxe                  | Efeito                                               |
| ------------------------ | ---------------------------------------------------- |
| `dominio.com`            | Vai pelo proxy padrão                                |
| `dominio.com +direct`    | Vai direto, sem proxy                                |
| `dominio.com +proxy:nome`| Vai por um perfil de proxy específico                |
| `dominio.com +block`     | Bloqueia a conexão                                   |
| `apps: a.exe, b`         | As regras abaixo valem só para esses apps            |
| `apps: *`                | As regras abaixo voltam a valer para todos os apps   |
| `! regra`                | Desativa a linha sem apagar                          |

- Avaliadas **de cima para baixo**: a primeira que casar vence.
- Alvos aceitos: `*.dominio.com`, IP exato ou faixa CIDR (`10.0.0.0/8`).

---

## Modos de funcionamento

**Explícito (padrão):** o app sobe servidores SOCKS5 e HTTP em `127.0.0.1` e aponta os
navegadores para eles com um arquivo PAC. Não precisa de administrador.

- **Windows:** configura o proxy do sistema, que Chrome, Edge e Firefox já seguem.
- **Linux (qualquer distro e ambiente gráfico):** configura direto os navegadores. No Firefox
  (e derivados, inclusive Flatpak/Snap) grava o PAC no `user.js` de cada perfil. No
  Chrome/Chromium/Edge/Brave/Vivaldi/Opera cria uma cópia do atalho do menu em
  `~/.local/share/applications` com `--proxy-pac-url`. Também configura o gsettings (GNOME) e o
  kioslaverc (KDE) para os outros apps. Tudo é desfeito quando o motor para.
  **Feche e abra o navegador pelo menu** depois de ligar o motor.

**Transparente** (aba **Configurações**): intercepta as conexões TCP no nível do sistema, o que
pega até os apps que ignoram o proxy do sistema. Usa `nftables` no Linux e WinDivert no Windows.
**Exige administrador/root**: gere o executável com a opção de admin (veja abaixo).

---

## Gerar executável

Gera um executável que roda sem Python instalado. Os scripts usam o `uv` se ele estiver
instalado; senão, criam/usam o `.venv` com o `pip`.

**Windows**: gera `dist\ProxyManager.exe`.

```powershell
.\scripts\build_windows.ps1          # roda como usuário comum
.\scripts\build_windows.ps1 -Admin   # pede UAC ao abrir (só para o modo transparente)
```

**Linux** (rode numa máquina Linux): gera `dist/proxy-manager`.

```bash
./scripts/build_linux.sh                    # só gera o executável
./scripts/build_linux.sh --install          # instala para o seu usuário, com atalho no menu (sem sudo)
./scripts/build_linux.sh --install --admin  # instala em /opt com atalho que pede senha via pkexec
                                            # (só para o modo transparente)
./scripts/build_linux.sh --uninstall        # remove a instalação do seu usuário
```

---

## Desenvolvimento

| Comando                  | O que faz                     |
| ------------------------ | ----------------------------- |
| `uv run pytest`          | Roda os testes                |
| `uv add <pacote>`        | Adiciona uma dependência      |
| `uv remove <pacote>`     | Remove uma dependência        |
| `uv sync --upgrade`      | Atualiza as dependências      |

Não edite o `uv.lock` à mão: os comandos acima já atualizam ele junto com o `pyproject.toml`.

---

## Limitações conhecidas

- **Só TCP/IPv4.** QUIC/HTTP3 (UDP) não é interceptado. Se precisar, desative o QUIC no navegador
  (`chrome://flags/#enable-quic`).
- **SOCKS5 e domínios:** as regras por domínio só funcionam se o app enviar o hostname (remote
  DNS). Caso contrário, só as regras por IP/CIDR se aplicam.
- **Linux:** o Chrome e similares só recebem o proxy quando abertos pelo menu, pelo painel ou por
  um link clicado em outro app. Abrindo pelo terminal, use `--proxy-pac-url=<URL do PAC>`.
- **Não validado em máquina real:** o modo transparente no Windows e o empacotamento Linux ainda
  não foram testados. Teste com cautela antes de depender deles.
