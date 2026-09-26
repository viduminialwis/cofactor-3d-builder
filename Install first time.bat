@echo off
title Cofactor 3D Builder - first-time setup
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% --version >nul 2>nul
if errorlevel 1 goto nopython
echo Installing RDKit (needs internet, takes 1-3 minutes)...
%PY% -m pip install --user -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Done! Now double-click "Start Cofactor 3D.bat".
echo.
pause
goto end
:nopython
echo.
echo Python was not found on this computer.
echo 1. Download it from https://www.python.org/downloads/
echo 2. During installation, TICK "Add python.exe to PATH".
echo 3. Then double-click this file again.
echo.
pause
goto end
:failed
echo.
echo Installation failed. Take a screenshot of this window and ask for help.
pause
:end
