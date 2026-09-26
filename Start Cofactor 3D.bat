@echo off
title Cofactor 3D Builder - keep this window open
cd /d "%~dp0"
set "PY=python"
where python >nul 2>nul || set "PY=py"
%PY% cofactor3d_app.py
if errorlevel 1 goto failed
goto end
:failed
echo.
echo The tool stopped because of an error (details above and in error_log.txt).
echo If RDKit is missing, run "Install first time.bat" first.
echo.
pause
:end
