@echo off
echo.
echo ========================================
echo Получение ngrok URL
echo ========================================
echo.
timeout /t 2 /nobreak > nul
curl -s http://localhost:4040/api/tunnels > tunnels.json
powershell -Command "$json = Get-Content tunnels.json | ConvertFrom-Json; $url = $json.tunnels[0].public_url; Write-Host ''; Write-Host 'Ваш публичный URL:' -ForegroundColor Green; Write-Host $url -ForegroundColor Cyan; Write-Host ''; Write-Host 'Webhook URL для 360dialog:' -ForegroundColor Green; Write-Host ($url + '/webhook') -ForegroundColor Cyan; Write-Host ''"
del tunnels.json
echo.
pause

