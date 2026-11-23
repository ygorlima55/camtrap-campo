@echo off
chcp 65001 >nul
title Instalacao - CamTrap Campo
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\instalar.ps1" %*
