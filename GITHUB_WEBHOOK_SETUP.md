# Настройка автоматического обновления через GitHub Webhook

Этот документ описывает настройку автоматического обновления бота при push в GitHub.

## Шаг 1: Настройка на сервере

### 1.1. Скопируйте скрипт обновления на сервер

```bash
# На вашем локальном компьютере
scp update_bot.sh root@164.92.182.134:/root/bot/
```

### 1.2. Сделайте скрипт исполняемым

```bash
# На сервере
ssh root@164.92.182.134
cd /root/bot
chmod +x update_bot.sh
```

### 1.3. Добавьте секрет в .env файл

```bash
# На сервере
cd /root/bot
nano .env
# Добавьте строку:
GITHUB_WEBHOOK_SECRET=ваш_случайный_секрет_здесь
```

Сгенерируйте случайный секрет:
```bash
openssl rand -hex 32
```

### 1.4. Перезапустите бота

```bash
# Если используется systemd
systemctl restart whatsapp-bot

# Если используется Docker
docker-compose restart

# Если запущен напрямую
pkill -f bot.py
nohup python bot.py > bot.log 2>&1 &
```

## Шаг 2: Настройка GitHub Webhook

### 2.1. Перейдите в настройки репозитория

1. Откройте ваш репозиторий на GitHub: `https://github.com/sunnuls/TERR_A`
2. Перейдите в **Settings** → **Webhooks**
3. Нажмите **Add webhook**

### 2.2. Заполните параметры webhook

- **Payload URL**: `http://164.92.182.134:8000/github-webhook`
  - Если у вас есть домен: `https://ваш-домен.com/github-webhook`
  - Если используете HTTPS: `https://164.92.182.134:8000/github-webhook`

- **Content type**: `application/json`

- **Secret**: Вставьте тот же секрет, который вы добавили в `.env` файл на сервере

- **Which events would you like to trigger this webhook?**: Выберите **Just the push event**

- **Active**: ✅ (включено)

### 2.3. Сохраните webhook

Нажмите **Add webhook**

## Шаг 3: Проверка работы

### 3.1. Тестовый push

Сделайте небольшое изменение в коде и выполните:

```bash
git add .
git commit -m "Test webhook"
git push origin main
```

### 3.2. Проверка логов на сервере

```bash
# На сервере
tail -f /root/bot/update.log
# или
tail -f /root/bot/bot.log
```

Вы должны увидеть сообщения об обновлении и перезапуске бота.

### 3.3. Проверка в GitHub

В настройках webhook на GitHub вы увидите последние доставки (Recent Deliveries). Если все настроено правильно, статус будет **200 OK**.

## Устранение проблем

### Webhook не срабатывает

1. Проверьте, что бот запущен и доступен:
   ```bash
   curl http://164.92.182.134:8000/github-webhook
   ```

2. Проверьте логи бота:
   ```bash
   tail -f /root/bot/bot.log
   ```

3. Проверьте логи обновления:
   ```bash
   tail -f /root/bot/update.log
   ```

### Ошибка "Invalid signature"

- Убедитесь, что секрет в `.env` файле совпадает с секретом в настройках GitHub webhook
- Перезапустите бота после изменения `.env`

### Бот не перезапускается

- Проверьте, что скрипт `update_bot.sh` исполняемый: `chmod +x update_bot.sh`
- Проверьте логи: `cat /root/bot/update.log`
- Убедитесь, что путь к директории бота правильный в скрипте

## Безопасность

⚠️ **Важно**: 
- Используйте HTTPS для webhook URL в продакшене
- Храните секрет в безопасности
- Не коммитьте `.env` файл в репозиторий
- Рассмотрите возможность использования firewall для ограничения доступа к `/github-webhook` endpoint

## Альтернатива: Использование ngrok для локальной разработки

Если нужно протестировать webhook локально:

```bash
ngrok http 8000
# Используйте полученный URL в настройках GitHub webhook
```

