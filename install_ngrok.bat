@echo off
echo ========================================
echo Установка ngrok
echo ========================================
echo.

cd /d "%~dp0"

echo Шаг 1: Скачивание ngrok...
powershell -Command "Invoke-WebRequest -Uri 'https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip' -OutFile 'ngrok.zip'"
echo ✓ Скачано

echo.
echo Шаг 2: Распаковка...
powershell -Command "Expand-Archive -Path 'ngrok.zip' -DestinationPath '.' -Force"
echo ✓ Распаковано

echo.
echo Шаг 3: Добавление authtoken...
ngrok.exe config add-authtoken 35AHD0uXOqdpknqpgDQFasCBxwU_3YaTfBwcR7znJVdBqJkv9
echo ✓ Authtoken добавлен

echo.
echo Шаг 4: Очистка...
del ngrok.zip
echo ✓ Готово

echo.
echo ========================================
echo ngrok установлен успешно!
echo ========================================
echo.
echo Теперь запустите:
echo   ngrok.exe http 8000
echo.
pause

