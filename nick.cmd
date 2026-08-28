@echo off
chcp 65001 >nul
rem Двойной клик — интерактивное меню. Из терминала:  nick "Ник" | nick -c | nick -p 2
if "%~1"=="" (
    python "%~dp0steam_nick.py" --menu
    if errorlevel 1 pause
) else (
    python "%~dp0steam_nick.py" %*
)
