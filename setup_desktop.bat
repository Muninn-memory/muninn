@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%.") do set "PROJECT_DIR=%%~fI"
set "LAUNCHER=%PROJECT_DIR%\launch_ravens.bat"
set "LINK_NAME=Ravens Control Panel"
set "SHORTCUT="

if not exist "%LAUNCHER%" (
    echo [ERROR] launch_ravens.bat not found:
    echo         %LAUNCHER%
    pause
    exit /b 1
)

for /f "usebackq delims=" %%S in (`powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = $null;" ^
  "try { $desktop = (New-Object -ComObject WScript.Shell).SpecialFolders.Item('Desktop') } catch {};" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = [Environment]::GetFolderPath('Desktop') };" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = [Environment]::GetFolderPath('DesktopDirectory') };" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) {" ^
  "  try {" ^
  "    $raw = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -Name Desktop -ErrorAction Stop).Desktop;" ^
  "    if ($raw) { $desktop = [Environment]::ExpandEnvironmentVariables($raw) }" ^
  "  } catch {}" ^
  "};" ^
  "if ([string]::IsNullOrWhiteSpace($desktop) -and $env:OneDrive) {" ^
  "  $candidate = Join-Path $env:OneDrive 'Desktop';" ^
  "  if (Test-Path -LiteralPath $candidate) { $desktop = $candidate }" ^
  "};" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' };" ^
  "if (-not (Test-Path -LiteralPath $desktop)) {" ^
  "  $publicDesktop = Join-Path $env:PUBLIC 'Desktop';" ^
  "  if (Test-Path -LiteralPath $publicDesktop) { $desktop = $publicDesktop }" ^
  "};" ^
  "if (-not (Test-Path -LiteralPath $desktop)) { throw ('Desktop folder not found or inaccessible: ' + $desktop) };" ^
  "$shortcutPath = Join-Path $desktop '%LINK_NAME%.lnk';" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sc = $ws.CreateShortcut($shortcutPath);" ^
  "$sc.TargetPath = 'cmd.exe';" ^
  "$sc.Arguments = '/c ""%LAUNCHER%""';" ^
  "$sc.WorkingDirectory = '%PROJECT_DIR%';" ^
  "$sc.Description = 'Ravens Control Panel - Muninn and Huginn';" ^
  "$sc.IconLocation = 'shell32.dll,22';" ^
  "$sc.WindowStyle = 7;" ^
  "$sc.Save();" ^
  "Write-Output $shortcutPath"`) do set "SHORTCUT=%%S"

if errorlevel 1 (
    echo [ERROR] Failed to create desktop shortcut.
    pause
    exit /b 1
)

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
