# Gera dist\ProxyManager.exe: standalone (não precisa de Python instalado na máquina de destino)
# e com UAC embutido -- pede elevação sozinho toda vez que for aberto, sem precisar de terminal
# elevado nem de atalho configurado manualmente.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv nao encontrado -- instale em https://docs.astral.sh/uv/getting-started/installation/"
}

# Garante o .venv com as dependencias do app + grupo "build" (PyInstaller) travadas no uv.lock.
uv sync --locked --group build
if ($LASTEXITCODE -ne 0) { throw "uv sync falhou" }

Write-Host "Gerando icone..."
uv run --no-sync python packaging\generate_icon.py
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o icone" }

Write-Host "`nRodando PyInstaller..."
uv run --no-sync python -m PyInstaller packaging\proxy_manager.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

Write-Host "`nExecutavel gerado em dist\ProxyManager.exe"
Write-Host "Ele pede elevacao (UAC) automaticamente toda vez que voce abrir -- nao precisa mais"
Write-Host "de terminal elevado nem de configurar 'Executar como administrador' no atalho."
