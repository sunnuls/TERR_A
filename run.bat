@echo off
REM Скрипт для запуска WhatsApp-бота и ngrok туннеля
REM Автоматически активирует виртуальное окружение и запускает оба процесса

echo ========================================
echo   WhatsApp Bot Startup Script
echo ========================================
echo.

REM Проверка наличия виртуального окружения
if exist .venv\Scripts\activate.bat (
    echo [OK] Найдено виртуальное окружение .venv
    echo [*] Активация venv...
    call .venv\Scripts\activate.bat
) else (
    echo [WARN] Виртуальное окружение .venv не найдено
    echo [*] Используется системный Python
)

echo.
echo [*] Запуск Flask-сервера...
echo.

REM Запускаем ngrok в отдельном окне
start "ngrok tunnel" cmd /k start_ngrok.bat

REM Задержка чтобы ngrok успел запуститься
timeout /t 2 /nobreak >nul

echo ========================================
echo   Bot is running and waiting for
echo   messages from WhatsApp
echo ========================================
echo.
echo [INFO] Flask server: http://0.0.0.0:8000
echo [INFO] Ngrok запущен в отдельном окне
echo [INFO] Для остановки нажмите Ctrl+C
echo.

REM Запускаем основное приложение
python bot.py

pause

