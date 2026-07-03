@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
)

start "" "http://localhost:8503"
"%PYTHON_EXE%" -m streamlit run app.py --server.port 8503 --server.headless true --browser.gatherUsageStats false

endlocal
