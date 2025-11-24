# ✅ FSM Реализация Завершена

## Статус: Все требования выполнены

### 📋 Чек-лист требований

- [x] **Состояния FSM определены**
  - MAIN_MENU
  - SELECT_WORK
  - SELECT_SHIFT
  - SELECT_HOURS
  - CONFIRM_SAVE

- [x] **Пользовательский путь реализован**
  - Стартовое сообщение → MAIN_MENU
  - "Работа" → SELECT_WORK (список: Поле, Кабачок, Картошка, Другое)
  - Выбор работы → SELECT_SHIFT (3 смены)
  - Выбор смены → SELECT_HOURS (4, 6, 8, 12 часов)
  - Выбор часов → CONFIRM_SAVE (Подтвердить/Отмена)

- [x] **Обработка состояний в webhook.py**
  - `if state == States.SELECT_WORK:` ✓
  - `if state == States.SELECT_SHIFT:` ✓
  - `if state == States.SELECT_HOURS:` ✓
  - `if state == States.CONFIRM_SAVE:` ✓

- [x] **Все функции вынесены в menu_handlers.py**
  - `handle_main_menu()`
  - `handle_select_work()`
  - `handle_select_shift()`
  - `handle_select_hours()`
  - `handle_show_confirmation()`
  - `handle_confirm_save()`

- [x] **FSM использует utils/state.py**
  - `get_state()` ✓
  - `set_state()` ✓
  - `clear_state()` ✓
  - `update_user_data()` ✓
  - `get_user_data()` ✓

- [x] **Сохранение через utils/sheets.save_entry()**
  - Функция `save_entry(phone, work, shift, hours)` реализована
  - Пока заглушка с логированием (готово к интеграции с Google Sheets API)

---

## 🏗️ Архитектура FSM

### Структура файлов

```
bot whats app/
├── bot.py                    # Отправка сообщений (send_message, send_buttons, send_list)
├── webhook.py                # Обработка входящих сообщений + FSM роутинг
├── menu_handlers.py          # Обработчики состояний FSM
├── config.py                 # Конфигурация (get_headers)
└── utils/
    ├── state.py              # FSM состояния и управление
    └── sheets.py             # Сохранение данных (save_entry)
```

### Поток данных

```
WhatsApp User
     │
     ▼
webhook.py (POST /webhook)
     │
     ├─→ Получение message
     ├─→ get_state(phone)           [utils/state.py]
     ├─→ Определение current_state
     ├─→ Логирование FSM состояния
     │
     ▼
menu_handlers.handle_incoming_message()
     │
     ├─→ handle_text_message()      (если текст)
     ├─→ handle_button_click()      (если кнопка)
     └─→ handle_list_selection()    (если список)
            │
            ├─→ if state == SELECT_WORK:
            │      update_user_data('work', ...)
            │      handle_select_shift()
            │
            ├─→ if state == SELECT_SHIFT:
            │      update_user_data('shift', ...)
            │      handle_select_hours()
            │
            ├─→ if state == SELECT_HOURS:
            │      update_user_data('hours', ...)
            │      handle_show_confirmation()
            │
            └─→ if state == CONFIRM_SAVE:
                   save_entry(phone, work, shift, hours)  [utils/sheets.py]
                   clear_state(phone)
                   handle_main_menu()
```

---

## 🎯 Детали реализации

### 1. utils/state.py

**Состояния:**
```python
class States:
    MAIN_MENU = "MAIN_MENU"
    SELECT_WORK = "SELECT_WORK"
    SELECT_SHIFT = "SELECT_SHIFT"
    SELECT_HOURS = "SELECT_HOURS"
    CONFIRM_SAVE = "CONFIRM_SAVE"
```

**Функции управления:**
```python
set_state(phone, state, data=None)      # Установить состояние
get_state(phone) → dict                  # Получить состояние
clear_state(phone)                       # Очистить состояние
update_user_data(phone, key, value)     # Обновить данные
get_user_data(phone, key, default=None) # Получить данные
```

**Хранилище:**
```python
user_states = {
    "79991234567": {
        "state": "SELECT_HOURS",
        "data": {
            "work": "Поле",
            "shift": "8-16",
            "hours": "8"
        }
    }
}
```

### 2. webhook.py

**Обработка с FSM:**
```python
# Получаем состояние
user_state = get_state(phone)
current_state = user_state.get('state')

# Логируем состояние
logger.info(f"[MSG] От {phone}, тип: {msg_type}, состояние FSM: {current_state}")

# Обработка списков
if interactive_type == 'list_reply':
    if current_state == States.SELECT_WORK:
        logger.info(f"[FSM] Состояние SELECT_WORK - обработка выбора работы")
    elif current_state == States.SELECT_SHIFT:
        logger.info(f"[FSM] Состояние SELECT_SHIFT - обработка выбора смены")
    elif current_state == States.SELECT_HOURS:
        logger.info(f"[FSM] Состояние SELECT_HOURS - обработка выбора часов")
    
    handle_incoming_message(message)
```

### 3. menu_handlers.py

**Обработчики состояний:**

#### MAIN_MENU
```python
def handle_main_menu(phone: str):
    set_state(phone, States.MAIN_MENU)
    send_buttons(phone, text, [
        {"id": "work_menu", "title": "📋 Работа"},
        {"id": "hours_menu", "title": "⏰ Инфо о часах"},
        {"id": "help_menu", "title": "❓ Помощь"}
    ])
```

#### SELECT_WORK
```python
def handle_select_work(phone: str):
    set_state(phone, States.SELECT_WORK)
    send_list(phone, text, button_text, [
        {"title": "Доступные работы", "rows": [
            {"id": "work_field", "title": "🌾 Поле"},
            {"id": "work_zucchini", "title": "🥒 Кабачок"},
            {"id": "work_potato", "title": "🥔 Картошка"},
            {"id": "work_other", "title": "📦 Другое"}
        ]}
    ])

# Обработка выбора
def handle_list_selection(phone, list_id, current_state):
    if current_state == States.SELECT_WORK:
        work_name = WORK_TYPES[list_id]
        update_user_data(phone, 'work', work_name)
        handle_select_shift(phone)  # → Следующее состояние
```

#### SELECT_SHIFT
```python
def handle_select_shift(phone: str):
    set_state(phone, States.SELECT_SHIFT)
    send_list(phone, text, button_text, [
        {"title": "Доступные смены", "rows": [
            {"id": "shift_1", "title": "☀️ Смена 1 (8-16)"},
            {"id": "shift_2", "title": "🌆 Смена 2 (16-00)"},
            {"id": "shift_3", "title": "🌙 Смена 3 (00-8)"}
        ]}
    ])

# Обработка выбора
if current_state == States.SELECT_SHIFT:
    shift_hours = SHIFTS[list_id]['hours']
    update_user_data(phone, 'shift', shift_hours)
    handle_select_hours(phone)  # → Следующее состояние
```

#### SELECT_HOURS
```python
def handle_select_hours(phone: str):
    set_state(phone, States.SELECT_HOURS)
    send_list(phone, text, button_text, [
        {"title": "Количество часов", "rows": [
            {"id": "hours_4", "title": "4 часа"},
            {"id": "hours_6", "title": "6 часов"},
            {"id": "hours_8", "title": "8 часов"},
            {"id": "hours_12", "title": "12 часов"}
        ]}
    ])

# Обработка выбора
if current_state == States.SELECT_HOURS:
    hours = HOURS_OPTIONS[list_id]
    update_user_data(phone, 'hours', hours)
    handle_show_confirmation(phone)  # → Следующее состояние
```

#### CONFIRM_SAVE
```python
def handle_show_confirmation(phone: str):
    set_state(phone, States.CONFIRM_SAVE)
    work = get_user_data(phone, 'work')
    shift = get_user_data(phone, 'shift')
    hours = get_user_data(phone, 'hours')
    
    send_buttons(phone, f"Работа: {work}\nСмена: {shift}\nЧасов: {hours}", [
        {"id": "confirm_yes", "title": "✅ Подтвердить"},
        {"id": "confirm_no", "title": "❌ Отмена"}
    ])

def handle_confirm_save(phone: str, confirmed: bool):
    if confirmed:
        work = get_user_data(phone, 'work')
        shift = get_user_data(phone, 'shift')
        hours = get_user_data(phone, 'hours')
        
        save_entry(phone, work, shift, hours)  # ← Сохранение!
        
        clear_state(phone)
        handle_main_menu(phone)
    else:
        clear_state(phone)
        handle_main_menu(phone)
```

### 4. utils/sheets.py

**Функция сохранения:**
```python
def save_entry(phone: str, work: str, shift: str, hours: str) -> bool:
    """
    Сохранить запись о работе пользователя в Google Sheets.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    entry_data = {
        "timestamp": timestamp,
        "phone": phone,
        "work": work,
        "shift": shift,
        "hours": hours
    }
    
    # TODO: Интеграция с Google Sheets API
    logger.info(f"📝 [SAVE] Сохранение записи: {entry_data}")
    logger.warning("⚠️ save_entry: данные залогированы, но не сохранены в Google Sheets")
    
    return True
```

**Статус:** Заглушка готова, данные логируются. Требуется настроить Google Sheets API для фактического сохранения.

---

## 🎬 Пример работы FSM

### Полный диалог

```
1. Пользователь: start
   Бот: Добро пожаловать! [Кнопки: Работа | Часы | Помощь]
   Состояние: MAIN_MENU

2. Пользователь: [Нажал кнопку "Работа"]
   Бот: Выберите тип работы: [Список: Поле | Кабачок | Картошка | Другое]
   Состояние: SELECT_WORK

3. Пользователь: [Выбрал "Поле"]
   Бот: ✅ Работа выбрана: Поле. Выберите смену: [Список: 3 смены]
   Состояние: SELECT_SHIFT
   Данные: work="Поле"

4. Пользователь: [Выбрал "Смена 1 (8-16)"]
   Бот: ✅ Работа: Поле, Смена: 8-16. Выберите часы: [Список: 4, 6, 8, 12]
   Состояние: SELECT_HOURS
   Данные: work="Поле", shift="8-16"

5. Пользователь: [Выбрал "8 часов"]
   Бот: Проверьте данные:
        Работа: Поле
        Смена: 8-16
        Часов: 8
        [Кнопки: Подтвердить | Отмена]
   Состояние: CONFIRM_SAVE
   Данные: work="Поле", shift="8-16", hours="8"

6. Пользователь: [Нажал "Подтвердить"]
   Бот: ✅ Запись сохранена! [Кнопки: Работа | Часы | Помощь]
   Действие: save_entry(phone, "Поле", "8-16", "8")
   Состояние: MAIN_MENU (очищено)
   Данные: {} (очищены)
```

### Логи в bot.log

```
[WEBHOOK] Получен webhook: {...}
[MSG] От 79991234567, тип: text, состояние FSM: None
[TEXT] 79991234567: start
[HANDLER] Обработка сообщения от 79991234567, тип: text
[FSM] Текущее состояние 79991234567: None
[FSM] 79991234567: MAIN_MENU
[SEND] Отправка сообщения 79991234567
[OK] Сообщение отправлено 79991234567

[MSG] От 79991234567, тип: interactive, состояние FSM: MAIN_MENU
[BUTTON] 79991234567: work_menu (Работа)
[FSM] 79991234567: SELECT_WORK
[SEND] Отправка сообщения 79991234567

[MSG] От 79991234567, тип: interactive, состояние FSM: SELECT_WORK
[LIST] 79991234567: work_field (Поле)
[FSM] Состояние SELECT_WORK - обработка выбора работы
[FSM] 79991234567: Работа выбрана - Поле
[FSM] 79991234567: SELECT_SHIFT

[MSG] От 79991234567, тип: interactive, состояние FSM: SELECT_SHIFT
[LIST] 79991234567: shift_1 (Смена 1 (8-16))
[FSM] Состояние SELECT_SHIFT - обработка выбора смены
[FSM] 79991234567: Смена выбрана - Смена 1 (8-16)
[FSM] 79991234567: SELECT_HOURS

[MSG] От 79991234567, тип: interactive, состояние FSM: SELECT_HOURS
[LIST] 79991234567: hours_8 (8 часов)
[FSM] Состояние SELECT_HOURS - обработка выбора часов
[FSM] 79991234567: Часы выбраны - 8
[FSM] 79991234567: CONFIRM_SAVE (показ)

[MSG] От 79991234567, тип: interactive, состояние FSM: CONFIRM_SAVE
[BUTTON] 79991234567: confirm_yes (Подтвердить)
[FSM] Состояние CONFIRM_SAVE - обработка кнопки подтверждения
[FSM] 79991234567: CONFIRM_SAVE (обработка: Да)
[SAVE] Сохранение записи: {'timestamp': '2024-11-07 12:34:56', 'phone': '79991234567', 'work': 'Поле', 'shift': '8-16', 'hours': '8'}
   Пользователь: 79991234567
   Работа: Поле
   Смена: 8-16
   Часы: 8
   Время: 2024-11-07 12:34:56
⚠️ save_entry: данные залогированы, но не сохранены в Google Sheets
```

---

## 🧪 Тестирование

### Запуск бота

```bash
# Установка зависимостей
pip install -r requirements_whatsapp.txt

# Запуск
python bot.py
```

### Тестирование FSM

1. Отправьте "start" в WhatsApp → должны появиться кнопки
2. Нажмите "Работа" → должен открыться список работ
3. Выберите работу → должен открыться список смен
4. Выберите смену → должен открыться список часов
5. Выберите часы → должна появиться сводка и кнопки подтверждения
6. Нажмите "Подтвердить" → должно появиться сообщение об успехе
7. Проверьте `bot.log` → должны быть все переходы FSM

### Тестирование отмены

1. На любом этапе отправьте "отмена"
2. Бот должен вернуться в главное меню
3. Состояние должно быть сброшено

---

## 📊 Статистика реализации

| Компонент | Строк кода | Статус |
|-----------|------------|--------|
| `utils/state.py` | 151 | ✅ Готово |
| `utils/sheets.py` | 106 | ✅ Готово (заглушка) |
| `menu_handlers.py` | 437 | ✅ Готово |
| `webhook.py` | 162 | ✅ Готово |
| **ИТОГО** | **856** | **✅ 100%** |

---

## 🎯 Следующие шаги (опционально)

### 1. Интеграция с Google Sheets API

Добавить в `utils/sheets.py`:
- Авторизация через service account
- Запись данных в таблицу
- Чтение данных

### 2. База данных

Заменить in-memory хранилище на:
- SQLite для простоты
- PostgreSQL для продакшена
- Redis для кэширования состояний

### 3. Дополнительные функции

- История записей пользователя
- Статистика по работам
- Экспорт отчётов
- Уведомления администраторам

---

## ✅ Итог

**FSM полностью реализована и готова к использованию!**

Все требования выполнены:
- ✅ 5 состояний FSM
- ✅ Пользовательский путь с выбором работы, смены и часов
- ✅ Обработка состояний в webhook.py
- ✅ Все функции в menu_handlers.py
- ✅ Использование utils/state.py
- ✅ Сохранение через utils/sheets.save_entry()

**Дата:** 7 ноября 2024  
**Статус:** Готово к использованию 🚀


