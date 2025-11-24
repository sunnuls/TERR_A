@echo off
echo ========================================
echo Установка Cloudflare Tunnel
echo ========================================
echo.
echo Скачивание cloudflared...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
echo.
echo Запуск туннеля...
cloudflared.exe tunnel --url http://localhost:8000
pause

