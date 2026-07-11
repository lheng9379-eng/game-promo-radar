@echo off
setlocal
cd /d "%~dp0"
if not exist logs\discovery mkdir logs\discovery
set PYTHONPATH=%CD%\src
set LOG_FILE=logs\discovery\search_discovery.log
echo [%date% %time%] start search discovery>> "%LOG_FILE%"
".venv\Scripts\python.exe" -m game_promo_radar.discovery search >> "%LOG_FILE%" 2>&1
set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] end search discovery exit=%EXIT_CODE%>> "%LOG_FILE%"
exit /b %EXIT_CODE%
