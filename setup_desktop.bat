@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "PROJECT_DIR=%%~fI"
set "LAUNCHER=%PROJECT_DIR%\launch_ravens.bat"
set "DESKTOP=%USERPROFILE%\Desktop"
set "LINK_NAME=Ravens Control Panel"
set "SHORTCUT=%DESKTOP%\%LINK_NAME%.lnk"

if not exist "%LAUNCHER%" (
    echo [ERROR] launch_ravens.bat not found:
    echo         %LAUNCHER%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sc = $ws.CreateShortcut('%SHORTCUT%');" ^
  "$sc.TargetPath = 'cmd.exe';" ^
  "$sc.Arguments = '/c ""%LAUNCHER%""';" ^
  "$sc.WorkingDirectory = '%PROJECT_DIR%';" ^
  "$sc.Description = 'Ravens Control Panel - Muninn and Huginn';" ^
  "$sc.IconLocation = 'shell32.dll,22';" ^
  "$sc.WindowStyle = 7;" ^
  "$sc.Save();"

if exist "%SHORTCUT%" (
    echo [OK] Shortcut created/updated:
    echo      %SHORTCUT%
) else (
    echo [ERROR] Failed to create desktop shortcut.
    pause
    exit /b 1
)

pause
exit /b 0

