@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

rem Resolve project directory from this script location
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "PROJECT_DIR=%%~fI"

if not exist "%PROJECT_DIR%\cli.py" (
    echo [ERROR] cli.py not found in:
    echo         %PROJECT_DIR%
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%\ravens_gui.py" (
    echo [ERROR] ravens_gui.py not found in:
    echo         %PROJECT_DIR%
    pause
    exit /b 1
)

if not exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found:
    echo         %PROJECT_DIR%\.venv\Scripts\python.exe
    echo.
    echo Create it with:
    echo   cd /d "%PROJECT_DIR%"
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

set "VENV_PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "VENV_PYW=%PROJECT_DIR%\.venv\Scripts\pythonw.exe"
set "VENV_PIP=%PROJECT_DIR%\.venv\Scripts\pip.exe"

rem Ensure customtkinter exists in the venv
"%VENV_PIP%" show customtkinter >nul 2>&1
if !errorlevel! neq 0 (
    echo Installing customtkinter in local venv...
    "%VENV_PIP%" install customtkinter --quiet
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install customtkinter.
        pause
        exit /b 1
    )
)

rem Launch GUI without console
if exist "%VENV_PYW%" (
    start "" "%VENV_PYW%" "%PROJECT_DIR%\ravens_gui.py"
) else (
    start "" "%VENV_PY%" "%PROJECT_DIR%\ravens_gui.py"
)

exit /b 0

