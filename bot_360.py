# bot_360.py - WhatsApp бот для 360dialog API
# Упрощенная версия с основным функционалом

import os
import sys
import logging
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# Импортируем 360dialog клиент
from whatsapp_360_client import WhatsApp360Client, Button

# Импортируем всю бизнес-логику из оригинального файла
# (БД, Google Sheets, etc.)
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, date
from typing import Dict, Optional
from pathlib import Path
import calendar

# Google Sheets API
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Загружаем конфиг
load_dotenv()
logging.basicConfig(level=logging.INFO)

# Настройки
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WA_BASE_URL = os.getenv("WA_BASE_URL", "https://waba-v2.360dialog.io")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
TZ = os.getenv("TZ", "Europe/Moscow").strip()
ADMIN_IDS = set(os.getenv("ADMIN_IDS", "").replace(" ", "").split(","))
DB_PATH = os.path.join(os.getcwd(), "reports_whatsapp.db")

# Google Sheets
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
OAUTH_CLIENT_JSON = os.getenv("OAUTH_CLIENT_JSON", "oauth_client.json")
TOKEN_JSON_PATH = Path(os.getenv("TOKEN_JSON_PATH", "token.json"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
EXPORT_PREFIX = os.getenv("EXPORT_PREFIX", "WorkLog")
AUTO_EXPORT_ENABLED = os.getenv("AUTO_EXPORT_ENABLED", "false").lower() == "true"
AUTO_EXPORT_CRON = os.getenv("AUTO_EXPORT_CRON", "0 9 * * 1")

if not WHATSAPP_TOKEN:
    logging.error("❌ WHATSAPP_TOKEN not found in .env")
    sys.exit(1)

# Инициализация Flask
app = Flask(__name__)

# Инициализация 360dialog клиента
wa = WhatsApp360Client(api_key=WHATSAPP_TOKEN, base_url=WA_BASE_URL)
logging.info("✅ 360dialog client initialized")

# Состояния пользователей (в памяти)
user_states: Dict[str, dict] = {}

def get_state(user_id: str) -> dict:
    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}
    return user_states[user_id]

def set_state(user_id: str, state: Optional[str], data: dict = None):
    s = get_state(user_id)
    s["state"] = state
    if data is not None:
        s["data"] = data

def clear_state(user_id: str):
    user_states[user_id] = {"state": None, "data": {}}

# БД функции (копируем из оригинала)
def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    # Упрощенная версия - создаем только основные таблицы
    with connect() as con, closing(con.cursor()) as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          user_id TEXT PRIMARY KEY,
          full_name TEXT,
          tz TEXT,
          created_at TEXT
        )
        """)
        con.commit()
    logging.info("✅ Database initialized")

def get_user(user_id: str):
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute("SELECT user_id, full_name, tz, created_at FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return None
        return {
            "user_id": r[0],
            "full_name": r[1],
            "tz": r[2] or TZ,
            "created_at": r[3],
        }

def upsert_user(user_id: str, full_name: Optional[str], tz: str):
    now = datetime.now().isoformat()
    with connect() as con, closing(con.cursor()) as c:
        row = c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            c.execute("UPDATE users SET full_name=?, tz=?, created_at=? WHERE user_id=?",
                      (full_name, tz, now, user_id))
        else:
            c.execute("INSERT INTO users(user_id, full_name, tz, created_at) VALUES(?,?,?,?)",
                      (user_id, full_name, tz, now))
        con.commit()

def is_admin(user_id: str) -> bool:
    return user_id in ADMIN_IDS

# Функции отправки сообщений
def show_main_menu(user_id: str, u: dict):
    """Показать главное меню"""
    name = (u or {}).get("full_name") or "—"
    text = f"👤 *{name}*\\n\\nВыберите действие:"
    buttons = [
        Button(title="🚜 Работа", callback_data="menu:work"),
        Button(title="📊 Статистика", callback_data="menu:stats"),
        Button(title="Ещё...", callback_data="menu:more"),
    ]
    wa.send_message(to=user_id, text=text, buttons=buttons)

# Обработчики сообщений
@wa.on_message
def handle_message(client, msg):
    """Обработка входящих текстовых сообщений"""
    user_id = msg.from_user.wa_id
    message_text = (msg.text or "").strip().lower()
    
    logging.info(f"📨 Message from {user_id}: {message_text}")
    
    # Команды
    if message_text in {"menu", "меню", "start", "старт"}:
        init_db()
        upsert_user(user_id, msg.from_user.name, TZ)
        u = get_user(user_id)
        
        if not u or not (u.get("full_name") or "").strip():
            set_state(user_id, "waiting_name")
            wa.send_message(to=user_id, text="👋 Для начала введите *Фамилию Имя* (например: *Иванов Иван*).")
            return
        
        show_main_menu(user_id, u)
        return
    
    # Обработка состояний
    state = get_state(user_id)
    current_state = state.get("state")
    
    if current_state == "waiting_name":
        # Пользователь вводит имя
        full_name = msg.text.strip()
        if len(full_name) < 3:
            wa.send_message(to=user_id, text="❌ Имя слишком короткое. Введите Фамилию и Имя.")
            return
        
        upsert_user(user_id, full_name, TZ)
        clear_state(user_id)
        u = get_user(user_id)
        wa.send_message(to=user_id, text=f"✅ Добро пожаловать, *{full_name}*!")
        show_main_menu(user_id, u)
        return
    
    # Неизвестная команда
    wa.send_message(to=user_id, text="🤖 Я вас не понял. Напишите *menu* или *start*.")

@wa.on_callback_button
def handle_callback(client, btn):
    """Обработка нажатий на кнопки"""
    user_id = btn.from_user.wa_id
    data = btn.data
    
    logging.info(f"🔘 Button from {user_id}: {data}")
    
    if data == "menu:root":
        u = get_user(user_id)
        show_main_menu(user_id, u)
    
    elif data == "menu:work":
        wa.send_message(to=user_id, text="🚜 Раздел \"Работа\" в разработке...")
    
    elif data == "menu:stats":
        wa.send_message(to=user_id, text="📊 Раздел \"Статистика\" в разработке...")
    
    elif data == "menu:more":
        buttons = [
            Button(title="📝 Перепись", callback_data="menu:edit"),
            Button(title="✏️ Имя", callback_data="menu:name"),
            Button(title="🔙 Назад", callback_data="menu:root"),
        ]
        wa.send_message(to=user_id, text="Доп. меню:", buttons=buttons)
    
    elif data == "menu:name":
        set_state(user_id, "waiting_name")
        wa.send_message(to=user_id, text="Введите новое *Фамилию Имя*:")
    
    else:
        wa.send_message(to=user_id, text=f"❌ Неизвестная команда: {data}")

# Webhook endpoint
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Webhook для приема сообщений от 360dialog"""
    if request.method == "GET":
        # Верификация
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if verify_token == VERIFY_TOKEN:
            logging.info("✅ Webhook verified")
            return challenge
        else:
            logging.error("❌ Invalid verify token")
            return "Invalid verify token", 403
    
    elif request.method == "POST":
        try:
            data = request.get_json()
            logging.info(f"[WEBHOOK] {data}")
            
            # Передаем в обработчик 360dialog клиента
            wa.process_webhook(data)
            
            return jsonify({"status": "ok"}), 200
        except Exception as e:
            logging.error(f"Error processing webhook: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

# Запуск
if __name__ == "__main__":
    init_db()
    
    logging.info("🤖 WhatsApp бот запущен!")
    logging.info(f"📡 Слушаю на {SERVER_HOST}:{SERVER_PORT}")
    logging.info(f"🔗 Webhook: http://{SERVER_HOST}:{SERVER_PORT}/webhook")
    
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
