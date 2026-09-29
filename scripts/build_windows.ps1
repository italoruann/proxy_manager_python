# Gera dist\ProxyManager.exe: standalone (nao precisa de Python instalado na maquina de destino).
# Antes, sempre fecha o Proxy Manager se estiver aberto e apaga o build anterior.
#
#   .\scripts\build_windows.ps1          -> roda como usuario comum (modo explicito/PAC)
#   .\scripts\build_windows.ps1 -Admin   -> pede UAC ao abrir (necessario so pro modo transparente)
#
# Usa o uv se estiver instalado; senao cria/usa o .venv com o pip.
param(
    [switch]$Admin
)
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Checked([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What falhou (codigo $LASTEXITCODE)" }
}

# O instalador do uv poe ele em ~\.local\bin, que nem sempre esta no PATH do terminal atual.
$Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $Uv) {
    $Uv = @("$HOME\.local\bin\uv.exe", "$HOME\.cargo\bin\uv.exe") | Where-Object { Test-Path $_ } |
        Select-Object -First 1
}

if ($Uv) {
    # Dependencias do app + grupo "build" (PyInstaller), travadas no uv.lock.
    Invoke-Checked "uv sync" { & $Uv sync --locked --group build }
    $Python = @($Uv, "run", "--no-sync", "python")
} else {
    $VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-Host "Criando .venv..."
        if (Get-Command py -ErrorAction SilentlyContinue) {
            Invoke-Checked "Criar o .venv" { py -3.14 -m venv .venv }
        } else {
            Invoke-Checked "Criar o .venv" { python -m venv .venv }
        }
    }
    # Um .venv criado pelo uv nao traz o pip.
    try { & $VenvPython -m pip --version *> $null; $HasPip = $LASTEXITCODE -eq 0 } catch { $HasPip = $false }
    if (-not $HasPip) { Invoke-Checked "ensurepip" { & $VenvPython -m ensurepip --upgrade } }
    Invoke-Checked "pip install" { & $VenvPython -m pip install --quiet -e . "pyinstaller>=6.16" }
    $Python = @($VenvPython)
}

function Invoke-Python([string]$What, [string[]]$Arguments) {
    $exe = $Python[0]
    $rest = @()
    if ($Python.Length -gt 1) { $rest = $Python[1..($Python.Length - 1)] }
    & $exe @rest @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What falhou (codigo $LASTEXITCODE)" }
}

# --- Remove a versao anterior -------------------------------------------------
# O .exe aberto fica travado pelo Windows e o PyInstaller nao consegue sobrescreve-lo. Fecha pela
# janela primeiro (sai pelo caminho normal, que desfaz o proxy do sistema); so forca se precisar.
$Running = @(Get-Process -Name ProxyManager -ErrorAction SilentlyContinue)
if ($Running) {
    Write-Host "Fechando o Proxy Manager em execucao..."
    foreach ($p in $Running) { [void]$p.CloseMainWindow() }
    $Deadline = (Get-Date).AddSeconds(10)
    while ((Get-Process -Name ProxyManager -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $Deadline)) {
        Start-Sleep -Milliseconds 300
    }
    $Left = @(Get-Process -Name ProxyManager -ErrorAction SilentlyContinue)
    if ($Left) {
        try {
            $Left | Stop-Process -Force -ErrorAction Stop
        } catch {
            throw "Nao consegui fechar o Proxy Manager em execucao (se ele foi aberto como administrador, feche-o pela bandeja ou rode este script como administrador)."
        }
        Start-Sleep -Seconds 1
        # Morto a forca ele nao desfez o proxy do sistema; desfaz aqui.
        Invoke-Python "Remover o proxy do sistema" @("-c",
            "from proxy_manager.core.system_integration import remove_system_proxy; print(remove_system_proxy(keep_browser_launchers=True)[1])")
    }
}

foreach ($Old in @("dist\ProxyManager.exe", "build")) {
    if (Test-Path $Old) {
        Write-Host "Removendo $Old anterior..."
        Remove-Item $Old -Recurse -Force
    }
}

Write-Host "`nGerando icone..."
Invoke-Python "Gerar o icone" @("packaging\generate_icon.py")

Write-Host "`nRodando PyInstaller..."
$env:PROXY_MANAGER_ADMIN = if ($Admin) { "1" } else { "0" }
try {
    Invoke-Python "PyInstaller" @("-m", "PyInstaller", "packaging\proxy_manager.spec", "--noconfirm",
                                  "--distpath", "dist", "--workpath", "build")
} finally {
    Remove-Item Env:PROXY_MANAGER_ADMIN -ErrorAction SilentlyContinue
}

Write-Host "`nExecutavel gerado em dist\ProxyManager.exe"
if ($Admin) {
    Write-Host "Ele pede elevacao (UAC) toda vez que for aberto (necessario pro modo transparente)."
} else {
    Write-Host "Roda como usuario comum. Para o modo transparente, gere com: .\scripts\build_windows.ps1 -Admin"
}
