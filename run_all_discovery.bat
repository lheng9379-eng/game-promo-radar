@echo off
setlocal
cd /d "%~dp0"
if not exist logs\discovery mkdir logs\discovery
set PYTHONPATH=%CD%\src
set LOG_FILE=logs\discovery\all_discovery.log
echo [%date% %time%] start all discovery>> "%LOG_FILE%"
".venv\Scripts\python.exe" -m game_promo_radar.discovery all >> "%LOG_FILE%" 2>&1
set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] end all discovery exit=%EXIT_CODE%>> "%LOG_FILE%"
exit /b %EXIT_CODE%
