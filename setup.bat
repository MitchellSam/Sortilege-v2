@echo off
setlocal

echo [1/4] Creating virtual environment...
uv venv --clear --python 3.11 .venv
if errorlevel 1 goto error

echo [2/4] Installing Python dependencies...
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if errorlevel 1 goto error

echo [3/4] Building React UI...
cd sortilege\ui
npm install
if errorlevel 1 goto error
npm run build
if errorlevel 1 goto error
cd ..\..

echo [4/4] Starting server and opening setup wizard...
start /B .venv\Scripts\python.exe -m uvicorn sortilege.api.routes:app --host 127.0.0.1 --port 8000
timeout /t 3 /nobreak >nul
start http://localhost:8000/setup

echo.
echo Sortilege server started. Open http://localhost:8000 to use the app.
goto end

:error
echo.
echo Setup failed. Check the error above.
pause
exit /b 1

:end
endlocal
