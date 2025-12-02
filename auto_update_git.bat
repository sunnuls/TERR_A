@echo off
setlocal

:: Получаем текущую дату и время для сообщения коммита
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set year=%datetime:~0,4%
set month=%datetime:~4,2%
set day=%datetime:~6,2%
set hour=%datetime:~8,2%
set minute=%datetime:~10,2%

set COMMIT_MSG="Auto-update: %day%.%month%.%year% %hour%:%minute%"

echo [INFO] Adding all changes...
git add .

echo [INFO] Committing changes with message: %COMMIT_MSG%
git commit -m %COMMIT_MSG%

echo [INFO] Pushing to origin main...
git push origin main

if %errorlevel% neq 0 (
    echo [ERROR] Failed to push changes.
    pause
    exit /b %errorlevel%
)

echo [SUCCESS] GitHub updated successfully!
pause

