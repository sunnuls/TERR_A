#!/bin/bash
# Скрипт для автоматического обновления и перезапуска бота
# Используется GitHub webhook

set -e

BOT_DIR="/root/bot"
LOG_FILE="/root/bot/update.log"

# Логирование
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=== Начало обновления ==="

cd "$BOT_DIR" || exit 1

# Обновление кода из GitHub
log "Обновление кода из GitHub..."
git fetch origin
git reset --hard origin/main
git pull origin main

# Проверка способа запуска и перезапуск
if systemctl is-active --quiet whatsapp-bot; then
    log "Перезапуск через systemd..."
    systemctl restart whatsapp-bot
    log "Бот перезапущен через systemd"
elif docker ps | grep -q bot; then
    log "Перезапуск через Docker..."
    cd "$BOT_DIR"
    docker-compose down
    docker-compose build --no-cache
    docker-compose up -d
    log "Бот перезапущен через Docker"
elif pgrep -f "bot.py" > /dev/null; then
    log "Перезапуск через kill + nohup..."
    pkill -f bot.py
    sleep 2
    cd "$BOT_DIR"
    nohup python bot.py > bot.log 2>&1 &
    log "Бот перезапущен через nohup"
else
    log "Бот не запущен, запускаю..."
    cd "$BOT_DIR"
    nohup python bot.py > bot.log 2>&1 &
    log "Бот запущен"
fi

log "=== Обновление завершено ==="

