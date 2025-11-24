# Руководство по миграции с Telegram на WhatsApp

## Обзор изменений

Этот документ описывает ключевые различия между Telegram и WhatsApp версиями бота.

## Сравнительная таблица

| Функция | Telegram версия | WhatsApp версия |
|---------|----------------|-----------------|
| Библиотека | aiogram 3.x | pywa |
| ID пользователя | Числовой ID | Номер телефона (строка) |
| База данных | reports.db | reports_whatsapp.db |
| FSM хранение | MemoryStorage (aiogram) | Словарь в памяти |
| Сообщения | Редактируемые | Только новые |
| Форматирование | HTML | Markdown |
| Кнопки | Unlimited | До 20 на сообщение |
| Webhook | Опционально | Обязательно |
| HTTPS | Опционально | Обязательно |

## Что изменилось в коде

### 1. Инициализация клиента

**Telegram:**
```python
from aiogram import Bot, Dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher()
```

**WhatsApp:**
```python
from pywa import WhatsApp
wa = WhatsApp(
    token=WHATSAPP_TOKEN,
    phone_id=WHATSAPP_PHONE_ID,
    server_host=SERVER_HOST,
    server_port=SERVER_PORT,
)
```

### 2. Обработчики сообщений

**Telegram:**
```python
@router.message(CommandStart())
async def cmd_start(message: Message):
    ...
```

**WhatsApp:**
```python
@wa.on_message(text.matches("start", ignore_case=True))
def cmd_start(client: WhatsApp, msg: WAMessage):
    ...
```

### 3. ID пользователей

**Telegram:**
```python
user_id: int = message.from_user.id  # Например: 123456789
```

**WhatsApp:**
```python
user_id: str = msg.from_user.wa_id  # Например: "79991234567"
```

### 4. Отправка сообщений с кнопками

**Telegram:**
```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Кнопка", callback_data="action")]
])
await bot.send_message(chat_id, text, reply_markup=keyboard)
```

**WhatsApp:**
```python
from pywa.types import Button

buttons = [Button(title="Кнопка", callback_data="action")]
client.send_message(to=user_id, text=text, buttons=buttons)
```

### 5. Форматирование текста

**Telegram (HTML):**
```python
text = "<b>Жирный</b> <i>курсив</i> <code>код</code>"
```

**WhatsApp (Markdown):**
```python
text = "*Жирный* _курсив_ `код`"
```

### 6. FSM (Finite State Machine)

**Telegram (aiogram):**
```python
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

class MyStates(StatesGroup):
    waiting = State()

@router.message(MyStates.waiting)
async def handler(message: Message, state: FSMContext):
    await state.clear()
```

**WhatsApp (ручное управление):**
```python
user_states = {}

def get_state(user_id: str) -> dict:
    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}
    return user_states[user_id]

def handle_text(client: WhatsApp, msg: WAMessage):
    state = get_state(msg.from_user.wa_id)
    if state["state"] == "waiting":
        # обработка
        clear_state(msg.from_user.wa_id)
```

## Миграция данных

### Если нужно перенести данные из Telegram версии:

```python
import sqlite3

# Подключаемся к обеим базам
tg_db = sqlite3.connect('reports.db')
wa_db = sqlite3.connect('reports_whatsapp.db')

# Создаём маппинг Telegram ID -> WhatsApp номер
user_mapping = {
    123456789: "79991234567",  # telegram_id: whatsapp_number
    987654321: "79997654321",
}

# Переносим пользователей
tg_cursor = tg_db.cursor()
wa_cursor = wa_db.cursor()

for tg_id, wa_number in user_mapping.items():
    user = tg_cursor.execute(
        "SELECT full_name, tz, created_at FROM users WHERE user_id=?",
        (tg_id,)
    ).fetchone()
    
    if user:
        wa_cursor.execute(
            "INSERT OR REPLACE INTO users(user_id, full_name, tz, created_at) VALUES(?,?,?,?)",
            (wa_number, user[0], user[1], user[2])
        )

# Переносим отчёты
for tg_id, wa_number in user_mapping.items():
    reports = tg_cursor.execute(
        """SELECT created_at, reg_name, location, location_grp, activity, 
           activity_grp, work_date, hours FROM reports WHERE user_id=?""",
        (tg_id,)
    ).fetchall()
    
    for r in reports:
        wa_cursor.execute(
            """INSERT INTO reports(created_at, user_id, reg_name, location, 
               location_grp, activity, activity_grp, work_date, hours) 
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (r[0], wa_number, r[1], r[2], r[3], r[4], r[5], r[6], r[7])
        )

wa_db.commit()
tg_db.close()
wa_db.close()

print("Миграция завершена!")
```

## Настройка окружения

### 1. Скопируйте настройки Google Sheets

```bash
# Если используете Google Sheets, скопируйте файлы авторизации
cp C:/bot/oauth_client.json ./
cp C:/bot/token.json ./
```

### 2. Создайте .env файл

```bash
cp env_whatsapp_example.txt .env
```

### 3. Заполните учётные данные WhatsApp

1. Перейдите на https://developers.facebook.com/
2. Создайте приложение типа "Business"
3. Добавьте продукт "WhatsApp"
4. Скопируйте токен и Phone Number ID в .env

### 4. Настройте админов

В файле .env укажите номера телефонов админов:
```
ADMIN_IDS=79991234567,79997654321
```

**Важно:** Формат номера - без плюса, начиная с кода страны.

## Тестирование

### 1. Локальный запуск

```bash
python bot_polya_whatsapp.py
```

### 2. Настройка ngrok для тестирования

```bash
# Установите ngrok: https://ngrok.com/
ngrok http 8000

# Скопируйте HTTPS URL (например: https://abc123.ngrok.io)
# Укажите его в настройках Webhook в Meta Developers:
# URL: https://abc123.ngrok.io/webhook
# Verify Token: значение из .env
```

### 3. Тестовое сообщение

Отправьте боту сообщение "start" с вашего WhatsApp номера.

## Продакшн развёртывание

### 1. Получите домен и SSL сертификат

WhatsApp требует HTTPS. Используйте:
- Let's Encrypt (бесплатно)
- Cloudflare (бесплатно)
- Ваш SSL провайдер

### 2. Настройте веб-сервер

**Nginx пример:**
```nginx
server {
    listen 443 ssl;
    server_name bot.yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 3. Создайте systemd service

```bash
sudo nano /etc/systemd/system/bot-whatsapp.service
```

```ini
[Unit]
Description=WhatsApp Bot Polya
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/bot_whats_app
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/python bot_polya_whatsapp.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable bot-whatsapp
sudo systemctl start bot-whatsapp
```

### 4. Обновите Webhook в Meta Developers

Укажите ваш HTTPS домен:
```
URL: https://bot.yourdomain.com/webhook
Verify Token: ваш_токен_из_env
```

## Мониторинг

### Проверка статуса

```bash
sudo systemctl status bot-whatsapp
```

### Логи

```bash
sudo journalctl -u bot-whatsapp -f
```

### База данных

```bash
sqlite3 reports_whatsapp.db "SELECT COUNT(*) FROM reports"
```

## Обратная совместимость

Если нужно запустить обе версии одновременно:

1. **Используйте разные базы данных** (уже настроено)
2. **Разные файлы .env** - создайте .env.telegram и .env.whatsapp
3. **Разные Google Sheets папки** - укажите разные DRIVE_FOLDER_ID
4. **Общие справочники** - можно синхронизировать activities и locations между базами

## Устранение неполадок

### Бот не отвечает
- Проверьте логи: `journalctl -u bot-whatsapp -n 100`
- Убедитесь, что webhook настроен правильно в Meta Developers
- Проверьте, что порт 8000 доступен: `netstat -tuln | grep 8000`

### Ошибки базы данных
```bash
# Проверка целостности
sqlite3 reports_whatsapp.db "PRAGMA integrity_check"

# Бэкап
cp reports_whatsapp.db reports_whatsapp_backup_$(date +%Y%m%d).db
```

### Проблемы с Google Sheets
```bash
# Удалите старый токен и авторизуйтесь заново
rm token.json
python bot_polya_whatsapp.py
# Следуйте инструкциям в консоли
```

## Полезные ссылки

- [WhatsApp Business Cloud API Документация](https://developers.facebook.com/docs/whatsapp/cloud-api)
- [PyWA Documentation](https://github.com/david-lev/pywa)
- [Meta Developers Console](https://developers.facebook.com/)
- [Google Sheets API](https://developers.google.com/sheets/api)

## Поддержка

При возникновении проблем:
1. Проверьте логи бота
2. Убедитесь, что все зависимости установлены
3. Проверьте настройки .env
4. Создайте issue с описанием проблемы




