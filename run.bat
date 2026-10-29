@echo off
chcp 65001 >nul
title CamTrap Campo
cd /d "%~dp0"
echo Abrindo o CamTrap Campo no navegador... (deixe esta janela aberta enquanto usar)
uv run --no-dev camtrap-campo
pause
