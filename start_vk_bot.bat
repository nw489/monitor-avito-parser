@echo off
chcp 65001 >nul 2>&1
D:
cd \avito-monitor

echo ========================================
echo   Дозорный VK-бот - Starting
echo ========================================
echo.
echo Current folder: %cd%
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH!
    pause
    exit /b 1
)

echo Installing dependencies...
pip install -r requirements.txt >nul 2>&1
echo Done.

echo Starting VK bot...
python vk_bot.py

pause
