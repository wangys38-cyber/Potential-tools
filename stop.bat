@echo off
echo Stopping Potential-tools...
taskkill /F /IM pythonw.exe 2>nul
taskkill /F /IM python.exe 2>nul
echo Potential-tools stopped.
timeout /t 2 >nul
