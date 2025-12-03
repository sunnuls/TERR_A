# config.py
"""
Конфигурация бота из переменных окружения.
"""
import os
from dotenv import load_dotenv

# Загрузка переменных из .env
load_dotenv()

# 360dialog API настройки
D360_API_KEY = os.getenv("D360_API_KEY")
D360_BASE_URL = os.getenv("D360_BASE_URL", "https://waba-v2.360dialog.io")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "876646062208778")  # Из скриншота 360dialog

# Google Sheets настройки
SHEETS_CREDENTIALS = os.getenv("SHEETS_CREDENTIALS", "")  # Base64 encoded JSON или путь к файлу
SHEET_ID = os.getenv("SHEET_ID", "")
SHEETS_ENABLED = os.getenv("SHEETS_ENABLED", "true").lower() == "true"

# Сервер настройки
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# Админы (номера телефонов)
ADMIN_IDS = os.getenv("ADMIN_IDS", "").split(",")
ADMIN_IDS = [admin_id.strip() for admin_id in ADMIN_IDS if admin_id.strip()]

# TIM (Первый зам директора по ИТ)
TIM_IDS = os.getenv("TIM_IDS", "").split(",")
TIM_IDS = [tim_id.strip() for tim_id in TIM_IDS if tim_id.strip()]

# База данных
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

# Таймзона
TZ = os.getenv("TZ", "Europe/Moscow")

# Проверка обязательных параметров
if not D360_API_KEY:
    raise ValueError("ERROR: D360_API_KEY not found in .env file!")

if not VERIFY_TOKEN:
    raise ValueError("ERROR: VERIFY_TOKEN not found in .env file!")

def get_headers():
    """
    Возвращает заголовки для запросов к 360dialog API.
    
    Returns:
        dict: Словарь с заголовками
    """
    return {
        "Content-Type": "application/json",
        "D360-API-KEY": D360_API_KEY
    }


print("[OK] Configuration loaded successfully")
print(f"[API] 360dialog API URL: {D360_BASE_URL}")
print(f"[KEY] API Key: {D360_API_KEY[:10]}...")
print(f"[ADM] Admins count: {len(ADMIN_IDS)}")

