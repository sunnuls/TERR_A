# 📡 API Usage Guide - 360dialog Integration

## ✅ Реализованные функции

### 1. config.py

```python
from config import get_headers

# Получить заголовки для запросов
headers = get_headers()
# Returns: {'Content-Type': 'application/json', 'D360-API-KEY': 'your_key'}
```

### 2. bot.py - Отправка сообщений

#### 2.1 send_message() - Базовая отправка

```python
from bot import send_message

# Отправить текстовое сообщение
data = {
    "type": "text",
    "text": {
        "body": "Привет!"
    }
}
success = send_message("79991234567", data)
# Returns: True если успешно
```

#### 2.2 send_buttons() - Интерактивные кнопки

```python
from bot import send_buttons

# Отправить сообщение с кнопками (максимум 3)
buttons = [
    {"id": "btn1", "title": "Кнопка 1"},
    {"id": "btn2", "title": "Кнопка 2"},
    {"id": "btn3", "title": "Кнопка 3"}
]
success = send_buttons("79991234567", "Выберите действие:", buttons)
```

#### 2.3 send_list() - Список с элементами

```python
from bot import send_list

# Отправить список
sections = [
    {
        "title": "Категория 1",
        "rows": [
            {
                "id": "row1",
                "title": "Элемент 1",
                "description": "Описание элемента 1"
            },
            {
                "id": "row2",
                "title": "Элемент 2",
                "description": "Описание элемента 2"
            }
        ]
    }
]
success = send_list("79991234567", "Выберите из списка:", "Открыть список", sections)
```

### 3. webhook.py - Обработка входящих сообщений

Webhook автоматически обрабатывает три типа сообщений:

#### 3.1 Текстовые сообщения

```json
{
  "messages": [{
    "from": "79991234567",
    "type": "text",
    "text": {"body": "Hello"}
  }]
}
```

Обрабатывается функцией `handle_text_message(phone, text)`

#### 3.2 Ответы на кнопки (button_reply)

```json
{
  "messages": [{
    "from": "79991234567",
    "type": "interactive",
    "interactive": {
      "type": "button_reply",
      "button_reply": {
        "id": "btn1",
        "title": "Кнопка 1"
      }
    }
  }]
}
```

Обрабатывается функцией `handle_button_click(phone, button_id)`

#### 3.3 Ответы на список (list_reply)

```json
{
  "messages": [{
    "from": "79991234567",
    "type": "interactive",
    "interactive": {
      "type": "list_reply",
      "list_reply": {
        "id": "row1",
        "title": "Элемент 1"
      }
    }
  }]
}
```

Обрабатывается функцией `handle_list_selection(phone, list_id)`

### 4. menu_handlers.py - Обработчики меню

#### 4.1 handle_main_menu() - Главное меню

```python
from menu_handlers import handle_main_menu

# Показать главное меню с кнопками: Работа, Часы, Помощь
handle_main_menu("79991234567")
```

Отправляет интерактивные кнопки:
- **Работа** (work_menu) → открывает список смен
- **Часы** (hours_menu) → запрашивает ввод часов
- **Помощь** (help_menu) → показывает справку

#### 4.2 handle_shift_menu() - Меню смен

```python
from menu_handlers import handle_shift_menu

# Показать список доступных смен
handle_shift_menu("79991234567")
```

Отправляет list message с тремя сменами:
- **Смена 1 (8-16)** - Дневная смена с 08:00 до 16:00
- **Смена 2 (16-00)** - Вечерняя смена с 16:00 до 00:00
- **Смена 3 (00-8)** - Ночная смена с 00:00 до 08:00

### 5. utils/state.py - Управление состояниями

```python
from utils.state import set_user_state, get_user_state, clear_user_state

# Установить состояние
set_user_state("79991234567", "waiting_hours", {"step": 1})

# Получить состояние
state = get_user_state("79991234567")
# Returns: {"state": "waiting_hours", "data": {"step": 1}}

# Очистить состояние
clear_user_state("79991234567")
```

## 🔄 Поток обработки сообщений

```
1. Пользователь → WhatsApp
   ↓
2. 360dialog → POST /webhook (webhook.py)
   ↓
3. webhook.py определяет тип сообщения:
   • text → handle_text_message()
   • button_reply → handle_button_click()
   • list_reply → handle_list_selection()
   ↓
4. menu_handlers.py обрабатывает:
   • Проверяет состояние FSM (utils/state.py)
   • Выполняет бизнес-логику
   • Отправляет ответ через bot.py
   ↓
5. bot.py → POST {D360_BASE_URL}/v1/messages
   ↓
6. 360dialog → WhatsApp → Пользователь
```

## 📝 Примеры использования

### Пример 1: Отправка приветствия

```python
from bot import send_message

phone = "79991234567"
data = {
    "type": "text",
    "text": {
        "body": "Добро пожаловать в TERRA Bot!"
    }
}
send_message(phone, data)
```

### Пример 2: Главное меню с кнопками

```python
from bot import send_buttons

phone = "79991234567"
text = "Выберите действие:"
buttons = [
    {"id": "work_menu", "title": "Работа"},
    {"id": "hours_menu", "title": "Часы"},
    {"id": "help_menu", "title": "Помощь"}
]
send_buttons(phone, text, buttons)
```

### Пример 3: Список смен

```python
from bot import send_list

phone = "79991234567"
text = "Выберите смену для начала работы:"
button_text = "Выбрать смену"
sections = [
    {
        "title": "Доступные смены",
        "rows": [
            {
                "id": "shift_1",
                "title": "Смена 1 (8-16)",
                "description": "Дневная смена с 08:00 до 16:00"
            },
            {
                "id": "shift_2",
                "title": "Смена 2 (16-00)",
                "description": "Вечерняя смена с 16:00 до 00:00"
            },
            {
                "id": "shift_3",
                "title": "Смена 3 (00-8)",
                "description": "Ночная смена с 00:00 до 08:00"
            }
        ]
    }
]
send_list(phone, text, button_text, sections)
```

### Пример 4: Обработка нажатия кнопки

```python
from menu_handlers import handle_button_click

phone = "79991234567"
button_id = "work_menu"

# Автоматически вызывается при нажатии кнопки
handle_button_click(phone, button_id)
# → Откроет меню смен (send_list)
```

### Пример 5: Обработка выбора из списка

```python
from menu_handlers import handle_list_selection

phone = "79991234567"
list_id = "shift_1"

# Автоматически вызывается при выборе из списка
handle_list_selection(phone, list_id)
# → Сохранит смену и отправит подтверждение
```

### Пример 6: Работа с состояниями

```python
from utils.state import set_user_state, get_user_state
from menu_handlers import send_text_message

phone = "79991234567"

# Шаг 1: Запросить ввод часов
set_user_state(phone, "waiting_hours")
send_text_message(phone, "Введите количество часов:")

# Шаг 2: Пользователь отправляет "8"
# В handle_text_message автоматически проверяется состояние:
state = get_user_state(phone)
if state.get("state") == "waiting_hours":
    # Обработать ввод часов
    handle_hours_input(phone, "8")
```

## 🧪 Тестирование

### Тест отправки текста

```bash
python -c "
from bot import send_message
data = {'type': 'text', 'text': {'body': 'Test message'}}
result = send_message('79991234567', data)
print('Success!' if result else 'Failed')
"
```

### Тест отправки кнопок

```bash
python -c "
from bot import send_buttons
buttons = [
    {'id': 'btn1', 'title': 'Test Button 1'},
    {'id': 'btn2', 'title': 'Test Button 2'}
]
result = send_buttons('79991234567', 'Choose:', buttons)
print('Success!' if result else 'Failed')
"
```

### Тест главного меню

```bash
python -c "
from menu_handlers import handle_main_menu
handle_main_menu('79991234567')
print('Main menu sent!')
"
```

## 📊 Структура данных

### Формат сообщения от 360dialog

```json
{
  "messages": [
    {
      "from": "79991234567",
      "id": "wamid.HBgNMTIzNDU2Nzg5MDEyFQIAE...",
      "timestamp": "1234567890",
      "type": "text | interactive | image | ...",
      "text": {
        "body": "Hello World"
      },
      "interactive": {
        "type": "button_reply | list_reply",
        "button_reply": {
          "id": "button_id",
          "title": "Button Title"
        },
        "list_reply": {
          "id": "row_id",
          "title": "Row Title",
          "description": "Row Description"
        }
      }
    }
  ],
  "statuses": []
}
```

### Формат отправки в 360dialog

```json
{
  "recipient_type": "individual",
  "to": "79991234567",
  "type": "text | interactive",
  "text": {
    "body": "Message text"
  },
  "interactive": {
    "type": "button | list",
    "body": {
      "text": "Message text"
    },
    "action": {
      "buttons": [...],
      "button": "Button text",
      "sections": [...]
    }
  }
}
```

## 🔑 API Key Management

API ключ хранится в `.env` и загружается через `config.py`:

```python
# config.py
D360_API_KEY = os.getenv("D360_API_KEY")

def get_headers():
    return {
        "Content-Type": "application/json",
        "D360-API-KEY": D360_API_KEY
    }
```

Используется во всех запросах к 360dialog API.

## 🚀 Запуск и тестирование

### 1. Запустить бота

```bash
python bot.py
```

### 2. Проверить webhook (в другом терминале)

```bash
# Healthcheck
curl http://localhost:8000/health

# Верификация webhook
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=terra_bot_verify_token_2024&hub.challenge=test123"
```

### 3. Настроить ngrok

```bash
ngrok http 8000
# Скопировать HTTPS URL в 360dialog webhook settings
```

### 4. Протестировать с реальным номером

1. Отправьте боту: `start` или `menu`
2. Бот пришлёт главное меню с кнопками
3. Нажмите "Работа" → откроется список смен
4. Выберите смену → бот подтвердит выбор

## 📝 Логирование

Все действия логируются с префиксами:

- `[OK]` - успешная операция
- `[SEND]` - отправка сообщения
- `[WEBHOOK]` - получен webhook
- `[MSG]` - обработка сообщения
- `[TEXT]` - текстовое сообщение
- `[BUTTON]` - нажатие кнопки
- `[LIST]` - выбор из списка
- `[MENU]` - открытие меню
- `[SHIFT]` - выбор смены
- `[INPUT]` - ввод данных
- `[WARN]` - предупреждение
- `[ERROR]` - ошибка

Пример лога:

```
[OK] Configuration loaded successfully
[API] 360dialog API URL: https://waba-v2.360dialog.io
[WEBHOOK] Получен webhook: {...}
[MSG] От 79991234567, тип: text
[TEXT] 79991234567: start
[HANDLER] Обработка сообщения от 79991234567
[MENU] Главное меню для 79991234567
[SEND] Отправка сообщения 79991234567
[OK] Сообщение отправлено 79991234567
```

---

**Готово! Все функции реализованы и готовы к использованию! 🎉**

