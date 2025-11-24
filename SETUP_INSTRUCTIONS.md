# Инструкция по запуску бота

Для запуска `bot_360_full.py` необходимо выполнить следующие шаги:

## 1. Установка зависимостей

В проекте не хватало некоторых библиотек. Я создал файл `requirements_full.txt`. Установите их командой:

```bash
pip install -r requirements_full.txt
```

## 2. Настройка переменных окружения (.env)

Создайте файл `.env` в корневой папке проекта (`c:\proekt'i\terra--main\.env`) и заполните его следующим содержимым:

```ini
# --- Обязательные настройки 360dialog ---
# Ваш API ключ от 360dialog
WHATSAPP_TOKEN=your_whatsapp_token_here

# Токен верификации вебхука (придумайте любой, например terra123)
VERIFY_TOKEN=your_verify_token_here

# --- Настройки сервера ---
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
TZ=Europe/Moscow

# --- Администраторы (опционально) ---
# Номера телефонов через запятую (без +)
ADMIN_IDS=79991234567,79990000000

# --- Google Sheets (опционально) ---
# Если используете Google Таблицы, укажите пути к файлам ключей
OAUTH_CLIENT_JSON=oauth_client.json
TOKEN_JSON_PATH=token.json
DRIVE_FOLDER_ID=your_folder_id
```

## 3. Запуск

После настройки запустите бота командой:

```bash
python bot_360_full.py
```
