# Gera dist\ProxyManager.exe: standalone (não precisa de Python instalado na máquina de destino)
# e com UAC embutido -- pede elevação sozinho toda vez que for aberto, sem precisar de terminal
# elevado nem de atalho configurado manualmente.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

Write-Host "Gerando icone..."
& $Python packaging\generate_icon.py

Write-Host "`nRodando PyInstaller..."
& $Python -m PyInstaller packaging\proxy_manager.spec --noconfirm --distpath dist --workpath build

Write-Host "`nExecutavel gerado em dist\ProxyManager.exe"
Write-Host "Ele pede elevacao (UAC) automaticamente toda vez que voce abrir -- nao precisa mais"
Write-Host "de terminal elevado nem de configurar 'Executar como administrador' no atalho."
