@echo off
chcp 65001 >nul
title Instalacao - CamTrap Campo
cd /d "%~dp0"
echo ============================================================
echo  CamTrap Campo - instalacao (so precisa fazer uma vez)
echo ============================================================
echo.

where uv >nul 2>nul
if errorlevel 1 (
  echo [1/3] Instalando o "uv" (gerenciador do Python^)...
  winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo Nao foi possivel instalar o uv. Veja o README, secao "Problemas".
    pause & exit /b 1
  )
  echo Feche esta janela e rode install.bat de novo para continuar.
  pause & exit /b 0
)

echo [1/3] Preparando o Python e as bibliotecas (pode demorar alguns minutos)...
uv sync --no-dev
if errorlevel 1 ( echo Falha ao instalar as bibliotecas. & pause & exit /b 1 )

echo.
echo [2/3] Ferramentas opcionais (recomendadas). Responda S ou N.
call :ferramenta "ExifTool (metadados completos das fotos)" OliverBetz.ExifTool
call :ferramenta "FFmpeg (videos: duracao, data, audio)" Gyan.FFmpeg
call :ferramenta "Tesseract (leitura da faixa do rodape das fotos)" UB-Mannheim.TesseractOCR

echo.
echo [3/3] Pronto! Para usar, de dois cliques em run.bat
pause
exit /b 0

:ferramenta
set /p resp=Instalar %~1? [S/N]
if /i "%resp%"=="S" winget install --id %~2 -e --accept-source-agreements --accept-package-agreements
exit /b 0
