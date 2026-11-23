# Remove o programa e os atalhos. Os DADOS (fotos copiadas e banco) NÃO são apagados.
$ErrorActionPreference = "Continue"
$Destino = $PSScriptRoot
Write-Host "Isto remove o CamTrap Campo de: $Destino"
Write-Host "Suas fotos e o banco de dados NÃO serão apagados (ficam em $env:USERPROFILE\CamTrap Campo)."
$r = Read-Host "Continuar? [s/N]"
if ($r -notmatch '^[sS]') { exit 0 }
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath("Desktop")) "CamTrap Campo.lnk") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path ([Environment]::GetFolderPath("Programs")) "CamTrap Campo") -ErrorAction SilentlyContinue
Set-Location $env:TEMP
Remove-Item -Recurse -Force $Destino -ErrorAction SilentlyContinue
Write-Host "Pronto. FFmpeg, Tesseract e ExifTool continuam instalados (podem ser removidos em Configurações > Aplicativos)."
Read-Host "Pressione Enter para fechar" | Out-Null
