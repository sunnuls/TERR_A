#!/bin/bash
# Скрипт для настройки автозапуска бота и ngrok через systemd

BOT_DIR="/root/bot"
NGROK_DIR="/root/ngrok"  # или где установлен ngrok

echo "=== Настройка автозапуска бота и ngrok ==="
echo ""

# 1. Создание systemd сервиса для бота
echo "1. Создание systemd сервиса для бота..."
cat > /etc/systemd/system/whatsapp-bot.service << 'BOTEOF'
[Unit]
Description=WhatsApp Bot Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bot
Environment="PATH=/root/bot/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/root/bot/venv/bin/python /root/bot/bot.py
Restart=always
RestartSec=10
StandardOutput=append:/root/bot/bot.log
StandardError=append:/root/bot/bot_error.log

[Install]
WantedBy=multi-user.target
BOTEOF

echo "   ✅ Сервис whatsapp-bot.service создан"

# 2. Создание systemd сервиса для ngrok
echo ""
echo "2. Создание systemd сервиса для ngrok..."

# Проверка, где находится ngrok
NGROK_PATH=$(which ngrok 2>/dev/null || echo "/root/ngrok/ngrok")
if [ ! -f "$NGROK_PATH" ]; then
    echo "   ⚠️  Ngrok не найден. Укажите путь к ngrok:"
    read -p "   Путь к ngrok (или Enter для пропуска): " NGROK_PATH
    if [ -z "$NGROK_PATH" ] || [ ! -f "$NGROK_PATH" ]; then
        echo "   ⚠️  Ngrok сервис не будет создан"
    fi
fi

if [ -f "$NGROK_PATH" ]; then
    cat > /etc/systemd/system/ngrok.service << NGROKEOF
[Unit]
Description=Ngrok Tunnel Service
After=network.target whatsapp-bot.service
Requires=whatsapp-bot.service

[Service]
Type=simple
User=root
ExecStart=$NGROK_PATH http 8000 --log=stdout
Restart=always
RestartSec=10
StandardOutput=append:/root/bot/ngrok.log
StandardError=append:/root/bot/ngrok_error.log

[Install]
WantedBy=multi-user.target
NGROKEOF
    echo "   ✅ Сервис ngrok.service создан"
fi

# 3. Перезагрузка systemd
echo ""
echo "3. Перезагрузка systemd..."
systemctl daemon-reload
echo "   ✅ Systemd перезагружен"

# 4. Включение автозапуска
echo ""
echo "4. Включение автозапуска..."
systemctl enable whatsapp-bot.service
echo "   ✅ Автозапуск бота включен"

if [ -f "/etc/systemd/system/ngrok.service" ]; then
    systemctl enable ngrok.service
    echo "   ✅ Автозапуск ngrok включен"
fi

# 5. Запуск сервисов
echo ""
echo "5. Запуск сервисов..."
systemctl start whatsapp-bot.service
echo "   ✅ Бот запущен"

if [ -f "/etc/systemd/system/ngrok.service" ]; then
    sleep 3
    systemctl start ngrok.service
    echo "   ✅ Ngrok запущен"
fi

# 6. Проверка статуса
echo ""
echo "6. Проверка статуса..."
systemctl status whatsapp-bot.service --no-pager -l
echo ""
if [ -f "/etc/systemd/system/ngrok.service" ]; then
    systemctl status ngrok.service --no-pager -l
fi

echo ""
echo "=== Настройка завершена ==="
echo ""
echo "Полезные команды:"
echo "  systemctl status whatsapp-bot    - статус бота"
echo "  systemctl status ngrok           - статус ngrok"
echo "  systemctl restart whatsapp-bot   - перезапуск бота"
echo "  systemctl restart ngrok          - перезапуск ngrok"
echo "  journalctl -u whatsapp-bot -f    - логи бота"
echo "  journalctl -u ngrok -f           - логи ngrok"

