@echo off
chcp 65001 >nul 2>&1
D:
cd \avito-monitor

echo ========================================
echo   Avito Monitor - Starting
echo ========================================
echo.
echo Current folder: %cd%
echo.

:: Проверяем Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH!
    echo.
    echo Try specifying full path to Python in this file.
    pause
    exit /b 1
)

echo Python found:
where python
echo.
python --version
echo.

:: Устанавливаем зависимости (тихо)
echo Installing dependencies...
pip install -r requirements.txt >nul 2>&1
echo Done.

:: Запускаем сервер
echo Starting server...
start "Avito Monitor Server" cmd /k "chcp 65001 >nul && python main.py"

:: Ждём запуска
echo Waiting for server to start...
timeout /t 5 /nobreak >nul

:: Открываем браузер
echo Opening browser...
start "" http://localhost:8000

echo.
echo ========================================
echo   Server is running!
echo   Do not close the server window.
echo ========================================
echo.
echo This window can be closed.
timeout /t 5 >nul