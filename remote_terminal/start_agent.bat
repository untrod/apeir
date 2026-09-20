@echo off
REM Auto-start launcher: start both layers windowless (pythonw). Logs -> remote_terminal\*.log
REM Working dir = user home so remote 'ls' defaults to home, not system32.
cd /d "%USERPROFILE%"
set SCRIPT_DIR=%~dp0
if "%NOUS_PYTHONW%"=="" set NOUS_PYTHONW=pythonw.exe
REM Execution layer (Agent, port 8765)
start "" "%NOUS_PYTHONW%" "%SCRIPT_DIR%agent.py"
REM Command layer (Brain, port 8770)
start "" "%NOUS_PYTHONW%" "%SCRIPT_DIR%brain.py"
