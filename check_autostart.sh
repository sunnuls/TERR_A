#!/bin/bash
# Скрипт для проверки автозапуска бота и ngrok

echo "=== Проверка автозапуска бота ==="
echo ""

echo "1. Systemd сервисы для бота:"
systemctl list-units --type=service | grep -i bot || echo "   ❌ Сервисы не найдены"
systemctl list-units --type=service | grep -i whatsapp || echo "   ❌ Сервисы не найдены"

echo ""
echo "2. Systemd сервисы для ngrok:"
systemctl list-units --type=service | grep -i ngrok || echo "   ❌ Сервисы не найдены"

echo ""
echo "3. Crontab для root:"
crontab -l 2>/dev/null | grep -i bot || echo "   ❌ Записей в crontab нет"
crontab -l 2>/dev/null | grep -i ngrok || echo "   ❌ Записей в crontab нет"

echo ""
echo "4. /etc/rc.local:"
if [ -f /etc/rc.local ]; then
    grep -i bot /etc/rc.local || echo "   ❌ Записей нет"
    grep -i ngrok /etc/rc.local || echo "   ❌ Записей нет"
else
    echo "   ❌ Файл не существует"
fi

echo ""
echo "5. Текущие процессы:"
ps aux | grep bot.py | grep -v grep && echo "   ✅ Бот запущен" || echo "   ❌ Бот не запущен"
ps aux | grep ngrok | grep -v grep && echo "   ✅ Ngrok запущен" || echo "   ❌ Ngrok не запущен"

