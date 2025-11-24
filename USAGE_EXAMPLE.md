# Примеры использования 360dialog Cloud API

## Структура проекта

### 1. config.py - Конфигурация

```python
from config import get_headers

# Получить заголовки для API запросов
headers = get_headers()
# Возвращает:
# {
#     "Content-Type": "application/json",
#     "D360-API-KEY": "ваш_api_ключ"
# }
```

### 2. bot.py - Отправка сообщений

#### 2.1. Простое текстовое сообщение

```python
from bot import send_message

# Отправить текстовое сообщение
send_message("79991234567", {
    "type": "text",
    "text": {
        "body": "Привет! Это текстовое сообщение."
    }
})
```

#### 2.2. Интерактивные кнопки

```python
from bot import send_buttons

# Отправить сообщение с кнопками (максимум 3)
send_buttons(
    to="79991234567",
    text="Выберите действие:",
    buttons=[
        {"id": "work_menu", "title": "Работа"},
        {"id": "hours_menu", "title": "Часы"},
        {"id": "help_menu", "title": "Помощь"}
    ]
)
```

#### 2.3. Список (List Message)

```python
from bot import send_list

# Отправить список с вариантами
send_list(
    to="79991234567",
    text="Выберите смену:",
    button_text="Выбрать смену",
    sections=[
        {
            "title": "Доступные смены",
            "rows": [
                {
                    "id": "shift_1",
                    "title": "Смена 1 (8-16)",
                    "description": "Дневная смена"
                },
                {
                    "id": "shift_2",
                    "title": "Смена 2 (16-00)",
                    "description": "Вечерняя смена"
                },
                {
                    "id": "shift_3",
                    "title": "Смена 3 (00-8)",
                    "description": "Ночная смена"
                }
            ]
        }
    ]
)
```

### 3. webhook.py - Обработка входящих сообщений

Webhook автоматически обрабатывает:

#### 3.1. Текстовые сообщения

```json
{
    "messages": [{
        "from": "79991234567",
        "type": "text",
        "text": {
            "body": "Привет"
        }
    }]
}
```

#### 3.2. Ответы на кнопки (button_reply)

```json
{
    "messages": [{
        "from": "79991234567",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {
                "id": "work_menu",
                "title": "Работа"
            }
        }
    }]
}
```

#### 3.3. Ответы на списки (list_reply)

```json
{
    "messages": [{
        "from": "79991234567",
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {
                "id": "shift_1",
                "title": "Смена 1 (8-16)",
                "description": "Дневная смена"
            }
        }
    }]
}
```

### 4. menu_handlers.py - Обработчики меню

#### 4.1. Главное меню

```python
from menu_handlers import handle_main_menu

# Показать главное меню с кнопками
handle_main_menu("79991234567")
# Отправляет кнопки: "Работа", "Часы", "Помощь"
```

#### 4.2. Меню смен

```python
from menu_handlers import handle_shift_menu

# Показать список смен
handle_shift_menu("79991234567")
# Отправляет список:
# - Смена 1 (8-16)
# - Смена 2 (16-00)
# - Смена 3 (00-8)
```

#### 4.3. Обработка нажатий кнопок

```python
from menu_handlers import handle_button_click

# Обработать нажатие кнопки
handle_button_click("79991234567", "work_menu")
# Автоматически вызовет handle_shift_menu()
```

#### 4.4. Обработка выбора из списка

```python
from menu_handlers import handle_list_selection

# Обработать выбор из списка
handle_list_selection("79991234567", "shift_1")
# Автоматически вызовет handle_shift_selected()
```

### 5. utils/state.py - Управление состоянием

#### 5.1. Установить состояние

```python
from utils.state import set_state, set_user_state

# Оба варианта работают одинаково
set_state("79991234567", "waiting_hours")
set_user_state("79991234567", "waiting_hours")

# С дополнительными данными
set_state("79991234567", "shift_selected", {"shift": "1"})
```

#### 5.2. Получить состояние

```python
from utils.state import get_state, get_user_state

# Получить состояние пользователя
state = get_state("79991234567")
# Возвращает: {"state": "waiting_hours", "data": {}}

current_state = state.get('state')
# Возвращает: "waiting_hours"
```

#### 5.3. Очистить состояние

```python
from utils.state import clear_state, clear_user_state

# Очистить состояние
clear_state("79991234567")
# Состояние сбрасывается: {"state": None, "data": {}}
```

#### 5.4. Работа с данными состояния

```python
from utils.state import update_user_data, get_user_data

# Сохранить данные
update_user_data("79991234567", "shift", "1")
update_user_data("79991234567", "hours", 8)

# Получить данные
shift = get_user_data("79991234567", "shift")
hours = get_user_data("79991234567", "hours", default=0)
```

## Полный пример работы бота

### Сценарий 1: Выбор смены

1. Пользователь отправляет текст "start" или "меню"
2. Бот вызывает `handle_main_menu()` → отправляет кнопки
3. Пользователь нажимает кнопку "Работа" (id: `work_menu`)
4. Webhook получает `button_reply` с id: `work_menu`
5. Вызывается `handle_button_click("79991234567", "work_menu")`
6. Функция вызывает `handle_shift_menu()` → отправляет список смен
7. Пользователь выбирает "Смена 1 (8-16)" (id: `shift_1`)
8. Webhook получает `list_reply` с id: `shift_1`
9. Вызывается `handle_list_selection("79991234567", "shift_1")`
10. Функция вызывает `handle_shift_selected("79991234567", "1")`
11. Смена сохраняется в состояние: `set_state(phone, "shift_selected", {"shift": "1"})`
12. Бот отправляет подтверждение и возвращает в главное меню

### Сценарий 2: Учёт часов

1. Пользователь нажимает кнопку "Часы" (id: `hours_menu`)
2. Вызывается `handle_hours_menu()`
3. Устанавливается состояние: `set_state(phone, "waiting_hours")`
4. Бот просит ввести количество часов
5. Пользователь отправляет текст "8"
6. Webhook получает текстовое сообщение
7. Проверяется состояние: `get_state(phone)` → `"waiting_hours"`
8. Вызывается `handle_hours_input(phone, "8")`
9. Часы сохраняются, состояние очищается: `clear_state(phone)`
10. Бот отправляет подтверждение

## Диаграмма взаимодействия

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│              │         │              │         │              │
│  WhatsApp    │◄───────►│  webhook.py  │◄───────►│ menu_        │
│  (360dialog) │         │              │         │ handlers.py  │
│              │         │              │         │              │
└──────────────┘         └──────┬───────┘         └──────┬───────┘
                                │                        │
                                │                        │
                          ┌─────▼────────┐         ┌─────▼────────┐
                          │              │         │              │
                          │   bot.py     │         │ utils/       │
                          │   (send)     │         │ state.py     │
                          │              │         │              │
                          └──────────────┘         └──────────────┘
```

## Настройка переменных окружения (.env)

```env
# 360dialog API
D360_API_KEY=your_360dialog_api_key_here
D360_BASE_URL=https://waba-v2.360dialog.io
VERIFY_TOKEN=your_verify_token_here

# Сервер
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# Админы
ADMIN_IDS=79991234567,79997654321

# База данных
DB_PATH=bot_data.db

# Таймзона
TZ=Europe/Moscow
```

## Запуск бота

```bash
# Установка зависимостей
pip install -r requirements_whatsapp.txt

# Запуск бота
python bot.py
```

## Тестирование

```bash
# Проверка здоровья сервера
curl http://localhost:8000/health

# Тест верификации webhook
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=your_token&hub.challenge=test123"

# Тест отправки сообщения (из Python)
python -c "
from bot import send_message
send_message('79991234567', {
    'type': 'text',
    'text': {'body': 'Тест'}
})
"
```

## Ограничения 360dialog API

- **Кнопки (buttons)**: максимум 3 кнопки
- **Заголовок кнопки**: максимум 20 символов
- **Список (list)**: максимум 10 секций, 10 строк в секции
- **Заголовок строки списка**: максимум 24 символа
- **Описание строки списка**: максимум 72 символа

## Логирование

Все действия логируются в файл `bot.log` и в консоль:

```
2024-11-07 10:30:45 - __main__ - INFO - [SEND] Отправка сообщения 79991234567
2024-11-07 10:30:45 - __main__ - INFO - [OK] Сообщение отправлено 79991234567
2024-11-07 10:30:50 - webhook - INFO - [MSG] От 79991234567, тип: text
2024-11-07 10:30:50 - menu_handlers - INFO - [MENU] Главное меню для 79991234567
```

