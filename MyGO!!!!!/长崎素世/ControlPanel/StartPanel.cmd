@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0ControlPanel.exe" (
  start "" "%~dp0ControlPanel.exe"
  exit /b 0
)
where python >nul 2>nul
if errorlevel 1 (
  echo 请先安装 Python 3.10 或更高版本，并勾选 Add Python to PATH。
  pause
  exit /b 1
)
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0server.py"
  exit /b 0
)
python "%~dp0server.py"
