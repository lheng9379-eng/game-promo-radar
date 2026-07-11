@echo off
setlocal
cd /d "%~dp0"
if not exist logs\discovery mkdir logs\discovery
set PYTHONPATH=%CD%\src
set LOG_FILE=logs\discovery\public_sources.log
echo [%date% %time%] start public sources discovery>> "%LOG_FILE%"
".venv\Scripts\python.exe" -m game_promo_radar.discovery public-sources >> "%LOG_FILE%" 2>&1
set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] end public sources discovery exit=%EXIT_CODE%>> "%LOG_FILE%"
exit /b %EXIT_CODE%
