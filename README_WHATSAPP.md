# Bot Polya - WhatsApp версия

Это версия бота для учёта рабочего времени, адаптированная для WhatsApp Business API.

## Основные отличия от Telegram версии

1. **Платформа**: Использует WhatsApp Business Cloud API вместо Telegram Bot API
2. **База данных**: Отдельная БД `reports_whatsapp.db`
3. **Библиотека**: `pywa` вместо `aiogram`
4. **ID пользователей**: Номера телефонов вместо Telegram ID
5. **Webhook**: Требуется публичный HTTPS endpoint для получения сообщений

## Функциональность

Полностью сохранена функциональность оригинального бота:

- ✅ Регистрация пользователей (Фамилия Имя)
- ✅ Учёт рабочих часов (техника/ручная работа)
- ✅ Выбор локации (поля/склад)
- ✅ Статистика (сегодня, неделя)
- ✅ Редактирование записей за последние 24 часа
- ✅ Админ-панель (добавление/удаление работ и локаций)
- ✅ Автоматический экспорт в Google Sheets
- ✅ Ограничение 24 часа в сутки

## Установка

### 1. Создание WhatsApp Business приложения

1. Зарегистрируйтесь в [Meta for Developers](https://developers.facebook.com/)
2. Создайте новое приложение типа "Business"
3. Добавьте продукт "WhatsApp"
4. Получите:
   - **Access Token** (токен доступа)
   - **Phone Number ID** (ID номера телефона)
5. Настройте Webhook:
   - URL: `https://ваш-домен.com/webhook`
   - Verify Token: придумайте свой токен

### 2. Установка зависимостей

```bash
pip install -r requirements_whatsapp.txt
```

### 3. Настройка .env файла

Скопируйте `.env.whatsapp.example` в `.env` и заполните:

```bash
cp .env.whatsapp.example .env
```

Основные параметры:
- `WHATSAPP_TOKEN` - токен доступа из Meta Developers
- `WHATSAPP_PHONE_ID` - ID вашего WhatsApp номера
- `VERIFY_TOKEN` - токен для верификации webhook
- `ADMIN_IDS` - номера телефонов админов (формат: 79991234567)

### 4. Настройка Google Sheets (опционально)

Если нужен экспорт в Google Sheets:

1. Скопируйте файлы `oauth_client.json` и `token.json` из Telegram версии
2. Или настройте по инструкции из `GOOGLE_SHEETS_SETUP.md` оригинального бота

## Запуск

### Локальный запуск (для тестирования)

```bash
python bot_polya_whatsapp.py
```

Для локального тестирования используйте ngrok:

```bash
ngrok http 8000
```

Затем укажите полученный HTTPS URL в настройках Webhook в Meta Developers.

### Продакшн запуск

Рекомендуется использовать:

1. **Gunicorn** (для production):
```bash
gunicorn -w 4 -b 0.0.0.0:8000 bot_polya_whatsapp:wa.server
```

2. **Systemd service** (автозапуск):
```ini
[Unit]
Description=WhatsApp Bot Polya
After=network.target

[Service]
User=youruser
WorkingDirectory=/path/to/bot
ExecStart=/path/to/venv/bin/python bot_polya_whatsapp.py
Restart=always

[Install]
WantedBy=multi-user.target
```

3. **Nginx** (reverse proxy):
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Команды бота

Пользователи могут отправлять боту текстовые команды:

- `start` или `menu` - Главное меню
- `today` - Статистика за сегодня
- `my` - Статистика за неделю

## Использование

1. Напишите боту на WhatsApp номер, указанный в настройках
2. Отправьте `start` для регистрации
3. Введите Фамилию и Имя
4. Используйте кнопки меню для работы с ботом

## Структура базы данных

База данных `reports_whatsapp.db` содержит те же таблицы, что и Telegram версия:

- `users` - пользователи (user_id = номер телефона)
- `reports` - отчёты о работе
- `activities` - виды работ
- `locations` - локации
- `google_exports` - информация об экспортах
- `monthly_sheets` - месячные таблицы Google Sheets

## Различия в поведении

1. **Кнопки**: WhatsApp поддерживает до 20 кнопок на сообщение
2. **Форматирование**: Используется Markdown вместо HTML
3. **Редактирование сообщений**: WhatsApp не поддерживает редактирование, поэтому бот отправляет новые сообщения
4. **ID пользователей**: Используются номера телефонов в формате `79991234567`

## Админ-функции

Админы (номера из `ADMIN_IDS` в .env) имеют доступ к:

- Добавлению/удалению видов работ
- Добавлению/удалению локаций
- Экспорту данных в Google Sheets
- Просмотру статистики всех пользователей

## Автоматический экспорт

Можно настроить автоматический экспорт в Google Sheets по расписанию:

```env
AUTO_EXPORT_ENABLED=true
AUTO_EXPORT_CRON=0 9 * * 1  # Каждый понедельник в 9:00
```

## Безопасность

1. **HTTPS обязателен** - WhatsApp Business API требует HTTPS для webhook
2. **Verify Token** - защищает webhook от несанкционированного доступа
3. **Валидация подписи** - библиотека pywa автоматически проверяет подписи Meta

## Решение проблем

### Бот не отвечает
- Проверьте, что webhook правильно настроен в Meta Developers
- Убедитесь, что сервер доступен по HTTPS
- Проверьте логи: бот выводит все ошибки в консоль

### Ошибки Google Sheets
- Убедитесь, что файлы `oauth_client.json` и `token.json` на месте
- Проверьте права доступа к Google Drive папке

### База данных
- База создаётся автоматически при первом запуске
- Бэкапы рекомендуется делать регулярно

## Поддержка

Для вопросов и проблем создавайте issues в репозитории проекта.

## Лицензия

Та же, что и у оригинального бота Telegram.




