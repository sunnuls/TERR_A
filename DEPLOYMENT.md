# Развертывание бота на сервере 24/7

Полное руководство по развертыванию WhatsApp бота на VPS для круглосуточной работы.

## 📋 Требования

### Минимальные требования к серверу:
- **ОС**: Ubuntu 20.04+ / Debian 11+ / CentOS 8+
- **RAM**: 512 MB (рекомендуется 1 GB)
- **CPU**: 1 ядро
- **Диск**: 10 GB
- **Python**: 3.8+
- **Доступ**: SSH root или sudo

### Необходимые данные:
- IP адрес сервера
- Доменное имя (опционально, но рекомендуется)
- Данные от 360dialog (API ключ, Phone ID)
- Google Cloud credentials (если используете Google Sheets)

---

## 🚀 Быстрая установка (Ubuntu/Debian)

### 1. Подключение к серверу

```bash
ssh root@ваш_сервер_ip
```

### 2. Обновление системы

```bash
apt update && apt upgrade -y
```

### 3. Установка зависимостей

```bash
# Python и pip
apt install -y python3 python3-pip python3-venv

# Git
apt install -y git

# Nginx (для reverse proxy)
apt install -y nginx

# Certbot (для SSL)
apt install -y certbot python3-certbot-nginx
```

### 4. Создание пользователя для бота

```bash
# Создаем пользователя
useradd -m -s /bin/bash botuser

# Переключаемся на пользователя
su - botuser
```

### 5. Клонирование проекта

```bash
# Создаем директорию
mkdir -p /home/botuser/whatsapp-bot
cd /home/botuser/whatsapp-bot

# Копируем файлы (или клонируем из Git)
# Если у вас Git репозиторий:
# git clone https://your-repo.git .

# Или загружаем файлы через SCP с локальной машины:
# scp -r /path/to/local/bot/* botuser@server_ip:/home/botuser/whatsapp-bot/
```

### 6. Создание виртуального окружения

```bash
python3 -m venv venv
source venv/bin/activate
```

### 7. Установка зависимостей Python

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 8. Настройка .env файла

```bash
nano .env
```

Заполните все необходимые переменные:

```env
# WhatsApp 360dialog
WHATSAPP_TOKEN=your_360dialog_api_key
WHATSAPP_PHONE_ID=your_phone_id
VERIFY_TOKEN=your_secret_verify_token
WA_BASE_URL=https://waba-v2.360dialog.io

# Сервер
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Админы
ADMIN_IDS=79991234567,79997654321

# Google Sheets (опционально)
OAUTH_CLIENT_JSON=oauth_client.json
TOKEN_JSON_PATH=token.json
DRIVE_FOLDER_ID=your_folder_id
EXPORT_PREFIX=WorkLog
AUTO_EXPORT_ENABLED=true
AUTO_EXPORT_CRON=0 9 * * 1

# База данных
DB_PATH=reports_whatsapp.db

# Таймзона
TZ=Europe/Moscow
```

Сохраните (Ctrl+O, Enter, Ctrl+X).

### 9. Загрузка Google Sheets credentials (если используете)

```bash
# Загрузите oauth_client.json на сервер
# С локальной машины:
scp oauth_client.json botuser@server_ip:/home/botuser/whatsapp-bot/
```

### 10. Первый запуск (тестовый)

```bash
python bot.py
```

Если все работает, нажмите Ctrl+C для остановки.

---

## ⚙️ Настройка systemd для автозапуска

### 1. Выход из пользователя botuser

```bash
exit  # Возврат к root
```

### 2. Создание systemd service файла

```bash
nano /etc/systemd/system/whatsapp-bot.service
```

Вставьте следующее содержимое:

```ini
[Unit]
Description=WhatsApp Bot Service
After=network.target

[Service]
Type=simple
User=botuser
WorkingDirectory=/home/botuser/whatsapp-bot
Environment="PATH=/home/botuser/whatsapp-bot/venv/bin"
ExecStart=/home/botuser/whatsapp-bot/venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=append:/home/botuser/whatsapp-bot/bot.log
StandardError=append:/home/botuser/whatsapp-bot/bot_error.log

[Install]
WantedBy=multi-user.target
```

Сохраните (Ctrl+O, Enter, Ctrl+X).

### 3. Активация и запуск сервиса

```bash
# Перезагрузка systemd
systemctl daemon-reload

# Включение автозапуска
systemctl enable whatsapp-bot

# Запуск сервиса
systemctl start whatsapp-bot

# Проверка статуса
systemctl status whatsapp-bot
```

### 4. Управление сервисом

```bash
# Остановка
systemctl stop whatsapp-bot

# Перезапуск
systemctl restart whatsapp-bot

# Просмотр логов
journalctl -u whatsapp-bot -f

# Или просмотр файлов логов
tail -f /home/botuser/whatsapp-bot/bot.log
tail -f /home/botuser/whatsapp-bot/bot_error.log
```

---

## 🌐 Настройка Nginx и SSL

### 1. Создание конфигурации Nginx

```bash
nano /etc/nginx/sites-available/whatsapp-bot
```

Вставьте:

```nginx
server {
    listen 80;
    server_name your-domain.com;  # Замените на ваш домен

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. Активация конфигурации

```bash
# Создание символической ссылки
ln -s /etc/nginx/sites-available/whatsapp-bot /etc/nginx/sites-enabled/

# Проверка конфигурации
nginx -t

# Перезапуск Nginx
systemctl restart nginx
```

### 3. Установка SSL сертификата

```bash
# Получение сертификата Let's Encrypt
certbot --nginx -d your-domain.com

# Следуйте инструкциям на экране
# Выберите опцию перенаправления HTTP на HTTPS
```

Certbot автоматически обновит конфигурацию Nginx для HTTPS.

### 4. Автообновление сертификата

```bash
# Проверка автообновления
certbot renew --dry-run
```

Certbot автоматически настроит cron для обновления.

---

## 🔗 Настройка Webhook в 360dialog

### 1. Получение URL webhook

Ваш webhook URL будет:
```
https://your-domain.com/webhook
```

Или если без домена:
```
http://your-server-ip:8000/webhook
```

**⚠️ Важно**: 360dialog требует HTTPS для production. Используйте домен с SSL.

### 2. Настройка в 360dialog Hub

1. Войдите в [360dialog Hub](https://hub.360dialog.com/)
2. Выберите ваш канал
3. Перейдите в **Webhooks**
4. Установите:
   - **Webhook URL**: `https://your-domain.com/webhook`
   - **Verify Token**: тот же, что в `.env` файле
5. Нажмите **Verify and Save**

### 3. Проверка webhook

```bash
# Просмотр логов в реальном времени
journalctl -u whatsapp-bot -f
```

Отправьте тестовое сообщение боту в WhatsApp и проверьте логи.

---

## 🐳 Альтернатива: Docker развертывание

### 1. Установка Docker

```bash
# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Установка Docker Compose
apt install -y docker-compose
```

### 2. Создание Dockerfile

Файл `Dockerfile` уже должен быть в проекте:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов проекта
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
```

### 3. Создание docker-compose.yml

Файл `docker-compose.yml` уже должен быть в проекте:

```yaml
version: '3.8'

services:
  bot:
    build: .
    container_name: whatsapp-bot
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./reports_whatsapp.db:/app/reports_whatsapp.db
    restart: unless-stopped
    ports:
      - "8000:8000"
```

### 4. Запуск через Docker

```bash
# Сборка и запуск
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down

# Перезапуск
docker-compose restart
```

---

## 📊 Мониторинг и логирование

### 1. Просмотр логов systemd

```bash
# Последние 100 строк
journalctl -u whatsapp-bot -n 100

# Реальное время
journalctl -u whatsapp-bot -f

# За последний час
journalctl -u whatsapp-bot --since "1 hour ago"
```

### 2. Просмотр файлов логов

```bash
# Основной лог
tail -f /home/botuser/whatsapp-bot/bot.log

# Лог ошибок
tail -f /home/botuser/whatsapp-bot/bot_error.log
```

### 3. Ротация логов

Создайте файл `/etc/logrotate.d/whatsapp-bot`:

```bash
nano /etc/logrotate.d/whatsapp-bot
```

Содержимое:

```
/home/botuser/whatsapp-bot/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 botuser botuser
}
```

### 4. Мониторинг ресурсов

```bash
# Использование CPU и памяти
top -p $(pgrep -f "python bot.py")

# Или с помощью htop
htop
```

---

## 🔧 Обслуживание

### Обновление бота

```bash
# Остановка сервиса
systemctl stop whatsapp-bot

# Переключение на пользователя
su - botuser
cd /home/botuser/whatsapp-bot

# Активация venv
source venv/bin/activate

# Обновление кода (если Git)
git pull

# Обновление зависимостей
pip install -r requirements.txt --upgrade

# Выход
exit

# Запуск сервиса
systemctl start whatsapp-bot
```

### Резервное копирование

```bash
# Создание backup скрипта
nano /home/botuser/backup.sh
```

Содержимое:

```bash
#!/bin/bash
BACKUP_DIR="/home/botuser/backups"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup базы данных
cp /home/botuser/whatsapp-bot/reports_whatsapp.db $BACKUP_DIR/db_$DATE.db

# Backup .env
cp /home/botuser/whatsapp-bot/.env $BACKUP_DIR/env_$DATE.txt

# Удаление старых backup (старше 30 дней)
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
find $BACKUP_DIR -name "*.txt" -mtime +30 -delete

echo "Backup completed: $DATE"
```

Сделайте исполняемым:

```bash
chmod +x /home/botuser/backup.sh
```

Добавьте в crontab:

```bash
crontab -e -u botuser
```

Добавьте строку:

```
0 2 * * * /home/botuser/backup.sh >> /home/botuser/backup.log 2>&1
```

---

## 🔒 Безопасность

### 1. Настройка файрвола (UFW)

```bash
# Установка UFW
apt install -y ufw

# Разрешение SSH
ufw allow 22/tcp

# Разрешение HTTP/HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# Включение файрвола
ufw enable

# Проверка статуса
ufw status
```

### 2. Защита SSH

```bash
nano /etc/ssh/sshd_config
```

Измените:

```
PermitRootLogin no
PasswordAuthentication no  # Если используете SSH ключи
```

Перезапустите SSH:

```bash
systemctl restart sshd
```

### 3. Автоматические обновления безопасности

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
```

---

## ❓ Troubleshooting

### Бот не запускается

```bash
# Проверка статуса
systemctl status whatsapp-bot

# Просмотр ошибок
journalctl -u whatsapp-bot -n 50

# Проверка .env файла
cat /home/botuser/whatsapp-bot/.env

# Проверка прав доступа
ls -la /home/botuser/whatsapp-bot/
```

### Webhook не работает

```bash
# Проверка, что бот слушает порт
netstat -tulpn | grep 8000

# Проверка Nginx
nginx -t
systemctl status nginx

# Проверка логов Nginx
tail -f /var/log/nginx/error.log

# Тест webhook вручную
curl -X POST https://your-domain.com/webhook \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

### Google Sheets не работает

```bash
# Проверка наличия credentials
ls -la /home/botuser/whatsapp-bot/oauth_client.json

# Проверка логов
grep "SHEETS" /home/botuser/whatsapp-bot/bot.log

# Повторная авторизация
su - botuser
cd /home/botuser/whatsapp-bot
source venv/bin/activate
rm token.json
python bot.py  # Пройдите OAuth заново
```

### Высокое использование ресурсов

```bash
# Проверка процессов
top -p $(pgrep -f "python bot.py")

# Проверка размера БД
du -h /home/botuser/whatsapp-bot/reports_whatsapp.db

# Очистка старых логов
journalctl --vacuum-time=7d
```

---

## 📝 Checklist развертывания

- [ ] Сервер настроен и обновлен
- [ ] Python 3.8+ установлен
- [ ] Пользователь botuser создан
- [ ] Проект скопирован на сервер
- [ ] Виртуальное окружение создано
- [ ] Зависимости установлены
- [ ] .env файл настроен
- [ ] Google Sheets credentials загружены (если используется)
- [ ] Systemd service создан и активирован
- [ ] Бот запущен и работает
- [ ] Nginx настроен (если используется домен)
- [ ] SSL сертификат установлен
- [ ] Webhook настроен в 360dialog
- [ ] Тестовое сообщение отправлено и получено
- [ ] Логирование работает
- [ ] Backup настроен
- [ ] Файрвол настроен

---

## 🎯 Полезные команды

```bash
# Статус бота
systemctl status whatsapp-bot

# Перезапуск бота
systemctl restart whatsapp-bot

# Логи в реальном времени
journalctl -u whatsapp-bot -f

# Проверка использования ресурсов
htop

# Проверка дискового пространства
df -h

# Проверка открытых портов
netstat -tulpn

# Проверка процессов Python
ps aux | grep python
```

---

**Готово!** Ваш бот теперь работает 24/7 на сервере. 🎉
