@echo off
cd /d "D:\Potential-tools"
echo Starting Potential-tools (hidden window)...
start "" /B ".venv\Scripts\pythonw.exe" app.py
echo Potential-tools started on http://127.0.0.1:5000
timeout /t 3 >nul
