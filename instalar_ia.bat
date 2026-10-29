@echo off
chcp 65001 >nul
title Instalacao da IA - CamTrap Campo
cd /d "%~dp0"
echo ============================================================
echo  CamTrap Campo - instalacao da IA (opcional, uma vez so)
echo ============================================================
echo  Baixa cerca de 1 GB: PyTorch, SpeciesNet (Google) e os modelos
echo  (MegaDetector v5a + classificador de especies).
echo  Depois disso a IA funciona SEM internet.
echo.
set /p ok=Continuar? [S/N]
if /i not "%ok%"=="S" exit /b 0

echo [1/2] Instalando bibliotecas (PyTorch e SpeciesNet)...
uv sync --no-dev --group ia
if errorlevel 1 ( echo Falha ao instalar. Veja o README, secao "Problemas". & pause & exit /b 1 )

echo [2/2] Baixando os modelos (uma vez so)...
uv run --no-dev --group ia python -m camtrap_campo.ia.baixar_modelos
if errorlevel 1 ( echo Falha ao baixar os modelos. & pause & exit /b 1 )

echo.
echo Pronto! A IA esta instalada. Use o botao "Rodar IA" na pagina de cada importacao.
pause
