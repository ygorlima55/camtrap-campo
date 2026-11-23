# Instalador do CamTrap Campo para Windows (sem precisar de administrador, exceto o Tesseract, que pede permissão).
# Uso normal: dois cliques em "Instalar CamTrap Campo.cmd". Precisa de internet só durante a instalação.
#   Programa: %LOCALAPPDATA%\Programs\CamTrap Campo
#   Dados (fotos copiadas e banco): %USERPROFILE%\CamTrap Campo  — fora do OneDrive e mantidos ao reinstalar/desinstalar
param(
    [string]$Destino = (Join-Path $env:LOCALAPPDATA "Programs\CamTrap Campo"),
    [string]$PastaDados = (Join-Path $env:USERPROFILE "CamTrap Campo"),
    [switch]$SemIA,           # não instala a IA (~1 GB)
    [switch]$ComIA,           # instala a IA sem perguntar
    [switch]$SemFerramentas,  # não instala FFmpeg, Tesseract e ExifTool
    [switch]$SemAtalhos,      # não cria atalhos (usado nos testes)
    [switch]$Silencioso       # não pergunta nada nem pausa no fim
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Pacote = Split-Path -Parent $PSScriptRoot           # pasta do zip extraído
$Programa = Join-Path $Pacote "programa"
New-Item -ItemType Directory -Force $Destino | Out-Null
$Log = Join-Path $Destino "instalacao.log"
Start-Transcript -Path $Log -Append | Out-Null

function Passo($n, $total, $texto) { Write-Host ""; Write-Host "[$n/$total] $texto" -ForegroundColor Yellow }
function Ok($texto) { Write-Host "  OK  $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "  !   $texto" -ForegroundColor DarkYellow }
function Falhar($texto) {
    Write-Host ""; Write-Host "ERRO: $texto" -ForegroundColor Red
    Write-Host "O registro completo está em: $Log"
    Stop-Transcript | Out-Null
    if (-not $Silencioso) { Read-Host "Pressione Enter para fechar" | Out-Null }
    exit 1
}
function Temos-Winget { [bool](Get-Command winget -ErrorAction SilentlyContinue) }

function Achar-Uv {
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $candidatos = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe"),
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
    )
    $pacotes = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $pacotes) { $candidatos += (Get-ChildItem $pacotes -Recurse -Filter uv.exe -ErrorAction SilentlyContinue | ForEach-Object FullName) }
    foreach ($x in $candidatos) { if ($x -and (Test-Path $x)) { return $x } }
    return $null
}

Write-Host "============================================================" -ForegroundColor DarkGreen
Write-Host "  CamTrap Campo - instalação" -ForegroundColor DarkGreen
Write-Host "============================================================" -ForegroundColor DarkGreen
Write-Host "  Programa: $Destino"
Write-Host "  Dados:    $PastaDados"
if (-not (Test-Path (Join-Path $Programa "pyproject.toml"))) { Falhar "Pasta 'programa' não encontrada. Extraia o zip inteiro antes de instalar." }

$instalarIA = $ComIA.IsPresent
if (-not $SemIA -and -not $ComIA -and -not $Silencioso) {
    Write-Host ""
    Write-Host "A IA identifica animais nas fotos (SpeciesNet + MegaDetector). Baixa cerca de 1 GB uma vez só;"
    Write-Host "depois funciona sem internet. Pode instalar depois rodando o instalador de novo."
    $r = Read-Host "Instalar a IA agora? [S/n]"
    $instalarIA = -not ($r -match '^[nN]')
}
$total = 6

# 1. uv (gerencia o Python e as bibliotecas)
Passo 1 $total "Gerenciador do Python (uv)"
$uv = Achar-Uv
if (-not $uv) {
    if (Temos-Winget) {
        winget install --id astral-sh.uv -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
    } else {
        Aviso "winget não encontrado; usando o instalador oficial do uv (astral.sh)"
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Host
    }
    $uv = Achar-Uv
}
if (-not $uv) { Falhar "Não foi possível instalar o uv. Verifique a internet e rode o instalador de novo." }
Ok "uv em $uv"

# 2. Arquivos do programa (a pasta .venv é mantida para reinstalar mais rápido)
Passo 2 $total "Copiando o programa"
foreach ($velho in @("src", "pyproject.toml", "uv.lock", "README.md")) {
    $alvo = Join-Path $Destino $velho
    if (Test-Path $alvo) { Remove-Item -Recurse -Force $alvo }
}
Copy-Item -Recurse -Force (Join-Path $Programa "*") $Destino
Copy-Item -Force (Join-Path $PSScriptRoot "desinstalar.ps1") $Destino
New-Item -ItemType Directory -Force (Join-Path $PastaDados "Dados") | Out-Null
# no .cmd, o caminho padrão vai como %USERPROFILE% (evita problema de acentos no nome do usuário)
$dadosCmd = if ($PastaDados.StartsWith($env:USERPROFILE)) { "%USERPROFILE%" + $PastaDados.Substring($env:USERPROFILE.Length) } else { $PastaDados }
$abrir = @"
@echo off
chcp 65001 >nul
title CamTrap Campo
cd /d "%~dp0"
set "CAMTRAP_DADOS=$dadosCmd\Dados"
set "CAMTRAP_BANCO=$dadosCmd\camtrap.sqlite3"
echo Abrindo o CamTrap Campo no navegador... deixe esta janela aberta enquanto usar.
"%~dp0.venv\Scripts\camtrap-campo.exe" %*
if errorlevel 1 pause
"@
Set-Content -Path (Join-Path $Destino "CamTrap Campo.cmd") -Value $abrir -Encoding Default
$remover = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0desinstalar.ps1"
"@
Set-Content -Path (Join-Path $Destino "Desinstalar CamTrap Campo.cmd") -Value $remover -Encoding Default
Ok "programa em $Destino"

# 3. Python e bibliotecas
Passo 3 $total ("Python e bibliotecas" + $(if ($instalarIA) { " + IA (pode levar 10 a 30 min)" } else { "" }))
Push-Location $Destino
$env:UV_PROJECT_ENVIRONMENT = Join-Path $Destino ".venv"
$args_uv = @("sync", "--no-dev", "--frozen", "--python", "3.12")
if ($instalarIA) { $args_uv += @("--group", "ia") }
& $uv @args_uv
$codigo = $LASTEXITCODE
Pop-Location
if ($codigo -ne 0) { Falhar "Falha ao instalar as bibliotecas (uv sync). Verifique a internet e rode de novo." }
$py = Join-Path $Destino ".venv\Scripts\python.exe"
& $py -c "import camtrap_campo.web.app" 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Falhar "O programa não abriu no teste rápido." }
Ok "bibliotecas instaladas e testadas"

# 4. Ferramentas externas
Passo 4 $total "FFmpeg (vídeos), Tesseract (rodapé das fotos) e ExifTool (metadados)"
if ($SemFerramentas) {
    Aviso "pulado"
} elseif (-not (Temos-Winget)) {
    Aviso "winget não encontrado: instale manualmente FFmpeg, Tesseract-OCR e ExifTool (veja o LEIA-ME)."
} else {
    $ferramentas = @(
        @{ id = "Gyan.FFmpeg"; nome = "FFmpeg"; exe = "ffmpeg" },
        @{ id = "UB-Mannheim.TesseractOCR"; nome = "Tesseract"; exe = "tesseract" },
        @{ id = "OliverBetz.ExifTool"; nome = "ExifTool"; exe = "exiftool" }
    )
    foreach ($f in $ferramentas) {
        $ja = & $py -c "from camtrap_campo.config import localizar_ferramenta as l; print(l('$($f.exe)') or '')"
        if ($ja) { Ok "$($f.nome) já instalado"; continue }
        Write-Host "  instalando $($f.nome)..."
        winget install --id $f.id -e --silent --accept-source-agreements --accept-package-agreements | Out-Host
        if ($LASTEXITCODE -eq 0) { Ok "$($f.nome)" } else { Aviso "$($f.nome) não foi instalado (código $LASTEXITCODE); o resto funciona sem ele." }
    }
}

# 5. Modelos da IA
Passo 5 $total "Modelos da IA"
if ($instalarIA) {
    & $py -m camtrap_campo.ia.baixar_modelos
    if ($LASTEXITCODE -eq 0) { Ok "IA pronta (funciona sem internet daqui em diante)" } else { Aviso "os modelos não baixaram; rode o instalador de novo com internet." }
} else {
    Aviso "IA não instalada (o resto do programa funciona normalmente)"
}

# 6. Atalhos
Passo 6 $total "Atalhos"
if ($SemAtalhos) {
    Aviso "pulado"
} else {
    $icone = Join-Path $Destino "src\camtrap_campo\web\static\marca.ico"
    $shell = New-Object -ComObject WScript.Shell
    $menu = Join-Path ([Environment]::GetFolderPath("Programs")) "CamTrap Campo"
    New-Item -ItemType Directory -Force $menu | Out-Null
    $locais = @(
        @{ caminho = (Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrap Campo.lnk"); alvo = "CamTrap Campo.cmd" },
        @{ caminho = (Join-Path $menu "CamTrap Campo.lnk"); alvo = "CamTrap Campo.cmd" },
        @{ caminho = (Join-Path $menu "Desinstalar CamTrap Campo.lnk"); alvo = "Desinstalar CamTrap Campo.cmd" },
        @{ caminho = (Join-Path $menu "Pasta de dados.lnk"); alvo = $PastaDados }
    )
    foreach ($l in $locais) {
        $a = $shell.CreateShortcut($l.caminho)
        $a.TargetPath = if ([IO.Path]::IsPathRooted($l.alvo)) { $l.alvo } else { Join-Path $Destino $l.alvo }
        $a.WorkingDirectory = $Destino
        if ($l.alvo -like "*.cmd") { $a.IconLocation = "$icone,0"; $a.WindowStyle = 7 }
        $a.Save()
    }
    Ok "atalho na Área de Trabalho e no menu Iniciar"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkGreen
Write-Host "  Pronto! Abra pelo atalho 'CamTrap Campo' na Área de Trabalho." -ForegroundColor DarkGreen
Write-Host "  Os dados ficam em: $PastaDados" -ForegroundColor DarkGreen
Write-Host "============================================================" -ForegroundColor DarkGreen
Stop-Transcript | Out-Null
if (-not $Silencioso) { Read-Host "Pressione Enter para fechar" | Out-Null }
