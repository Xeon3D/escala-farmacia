@echo off
rem Arranca a Escala da Farmácia e abre o navegador.
cd /d "%~dp0"
python server.py %*
pause
