# Решение ошибки ngrok ERR_NGROK_334

## Проблема:
Ошибка `ERR_NGROK_334` означает, что туннель с таким URL уже запущен.

## Решение:

### Вариант 1: Остановить существующий ngrok

```powershell
# Найти и остановить все процессы ngrok
Get-Process -Name "ngrok" -ErrorAction SilentlyContinue | Stop-Process -Force

# Подождать 2-3 секунды
Start-Sleep -Seconds 3

# Запустить ngrok заново
ngrok http 8000
```

### Вариант 2: Использовать другой порт

Если нужно запустить несколько туннелей:

```powershell
# Первый туннель
ngrok http 8000

# Второй туннель (в другом окне)
ngrok http 8001 --domain=ваш-домен.ngrok-free.app
```

### Вариант 3: Использовать pooling (для балансировки)

```powershell
ngrok http 8000 --pooling-enabled
```

## Быстрое решение:

Выполните в PowerShell:

```powershell
# Остановить все ngrok
Get-Process ngrok -ErrorAction SilentlyContinue | Stop-Process -Force

# Подождать
Start-Sleep -Seconds 3

# Запустить заново
cd "C:\BOTIKI\bot whats app"
ngrok http 8000
```

## Проверка:

После запуска ngrok должен показать новый URL (он может отличаться от предыдущего).

Если URL изменился, обновите webhook в 360dialog с новым URL.

