@echo off
cd /d "%~dp0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5412 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
echo Starting Fresh Food Analyzer on http://127.0.0.1:5412 (close this window to stop it)
python app.py
pause
