# bot.py - WhatsApp бот с 360dialog API
# -*- coding: utf-8 -*-

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, date
from typing import Dict, Optional, Tuple, List, Callable, Any
from pathlib import Path
from dataclasses import dataclass
import calendar
import logging
import difflib

def find_best_match(user_input: str, items: List[Tuple[int, str]]) -> Optional[Tuple[int, str]]:
    """
    Ищет лучший вариант в списке (id, name).
    Поддерживает:
    1. Точное совпадение номера (1, 2, 3...)
    2. Нечеткий поиск по названию (difflib)
    """
    text = user_input.strip()
    if not text:
        return None
    
    # 1. Пробуем как число (номер в списке)
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(items):
            return items[idx]
    
    # 2. Пробуем нечеткий поиск по названию
    name_map = {item[1].lower(): item for item in items}
    matches = difflib.get_close_matches(text.lower(), name_map.keys(), n=1, cutoff=0.4)
    
    if matches:
        return name_map[matches[0]]
    
    return None

# Custom 360dialog client instead of pywa
from whatsapp_360_client import WhatsApp360Client, Button, MessageObject, CallbackObject
from dotenv import load_dotenv
from flask import Flask, request, jsonify

# Google Sheets API
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scheduler для автоматического экспорта
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# -----------------------------
# Конфиг
# -----------------------------

load_dotenv()
logging.basicConfig(level=logging.INFO)

# WhatsApp настройки
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
APP_SECRET = os.getenv("APP_SECRET")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
WA_BASE_URL = os.getenv("WA_BASE_URL", "https://waba-v2.360dialog.io")

# WA: critical env check
if not WHATSAPP_TOKEN:
    logging.error("❌ Ошибка: WHATSAPP_TOKEN не найден в .env")
    sys.exit(1)

if not WHATSAPP_PHONE_ID:
    logging.error("❌ Ошибка: WHATSAPP_PHONE_ID не найден в .env")
    sys.exit(1)

if not VERIFY_TOKEN:
    logging.error("VERIFY_TOKEN is not set in environment")
    sys.exit(1)

TZ = os.getenv("TZ", "Europe/Moscow").strip()

def _parse_admin_ids(s: str) -> List[str]:
    out = []
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        out.append(part.strip())
    return out

ADMIN_IDS = set(_parse_admin_ids(os.getenv("ADMIN_IDS", "")))
logging.info(f"🔧 ADMIN_IDS loaded: {ADMIN_IDS}")

DB_PATH = os.path.join(os.getcwd(), "reports_whatsapp.db")

# Google Sheets настройки
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
OAUTH_CLIENT_JSON = os.getenv("OAUTH_CLIENT_JSON", "oauth_client.json")
TOKEN_JSON_PATH = Path(os.getenv("TOKEN_JSON_PATH", "token.json"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
EXPORT_PREFIX = os.getenv("EXPORT_PREFIX", "WorkLog")

# Расписание автоматического экспорта
AUTO_EXPORT_ENABLED = os.getenv("AUTO_EXPORT_ENABLED", "false").lower() == "true"
AUTO_EXPORT_CRON = os.getenv("AUTO_EXPORT_CRON", "0 9 * * 1")

# -----------------------------
# Константы (дефолтные справочники)
# -----------------------------

DEFAULT_FIELDS = [
    "Северное","Фазенда","5 га","58 га","Фермерское","Сад",
    "Чеки №1","Чеки №2","Чеки №3","Рогачи (б)","Рогачи(М)",
    "Владимирова Аренда","МТФ",
]

DEFAULT_TECH = [
    "пахота","чизелевание","дискование","культивация сплошная",
    "культивация междурядная","опрыскивание","комбайн уборка","сев","барнование",
]

DEFAULT_HAND = [
    "прополка","сбор","полив","монтаж","ремонт",
]

GROUP_TECH = "техника"
GROUP_HAND = "ручная"
GROUP_FIELDS = "поля"
GROUP_WARE = "склад"

# -----------------------------
# Хранилище состояний пользователей (в памяти)
# -----------------------------

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

# -----------------------------
# БД (те же функции, что в Telegram версии)
# -----------------------------

def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    with connect() as con, closing(con.cursor()) as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          user_id    TEXT PRIMARY KEY,
          full_name  TEXT,
          tz         TEXT,
          created_at TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS activities(
          id    INTEGER PRIMARY KEY AUTOINCREMENT,
          name  TEXT UNIQUE,
          grp   TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS locations(
          id    INTEGER PRIMARY KEY AUTOINCREMENT,
          name  TEXT UNIQUE,
          grp   TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS reports(
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at    TEXT,
          user_id       TEXT,
          reg_name      TEXT,
          location      TEXT,
          location_grp  TEXT,
          activity      TEXT,
          activity_grp  TEXT,
          work_date     TEXT,
          hours         INTEGER
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS google_exports(
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id     INTEGER UNIQUE,
          spreadsheet_id TEXT,
          sheet_name    TEXT,
          row_number    INTEGER,
          exported_at   TEXT,
          last_updated  TEXT,
          FOREIGN KEY (report_id) REFERENCES reports(id)
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS monthly_sheets(
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          year          INTEGER,
          month         INTEGER,
          spreadsheet_id TEXT,
          sheet_url     TEXT,
          created_at    TEXT,
          UNIQUE(year, month)
        )
        """)

        def table_cols(table: str):
            return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}

        lcols = table_cols("locations")
        if "grp" not in lcols:
            c.execute("ALTER TABLE locations ADD COLUMN grp TEXT")
            c.execute("UPDATE locations SET grp=? WHERE (grp IS NULL OR grp='') AND name='Склад'", (GROUP_WARE,))
            c.execute("UPDATE locations SET grp=? WHERE (grp IS NULL OR grp='') AND name<>'Склад'", (GROUP_FIELDS,))

        acols = table_cols("activities")
        if "grp" not in acols:
            c.execute("ALTER TABLE activities ADD COLUMN grp TEXT")
            placeholders = ",".join("?" * len(DEFAULT_TECH))
            if placeholders:
                c.execute(
                    f"UPDATE activities SET grp=? WHERE (grp IS NULL OR grp='') AND name IN ({placeholders})",
                    (GROUP_TECH, *DEFAULT_TECH)
                )
            c.execute("UPDATE activities SET grp=? WHERE (grp IS NULL OR grp='')", (GROUP_HAND,))

        for name in DEFAULT_FIELDS:
            c.execute("INSERT OR IGNORE INTO locations(name, grp) VALUES (?, ?)", (name, GROUP_FIELDS))
        c.execute("INSERT OR IGNORE INTO locations(name, grp) VALUES (?, ?)", ("Склад", GROUP_WARE))

        for name in DEFAULT_TECH:
            c.execute("INSERT OR IGNORE INTO activities(name, grp) VALUES (?, ?)", (name, GROUP_TECH))
        for name in DEFAULT_HAND:
            c.execute("INSERT OR IGNORE INTO activities(name, grp) VALUES (?, ?)", (name, GROUP_HAND))

        con.commit()

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

def list_activities(grp: str) -> List[str]:
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("SELECT name FROM activities WHERE grp=? ORDER BY name", (grp,)).fetchall()
        return [r[0] for r in rows]

def list_activities_with_id(grp: str) -> List[Tuple[int, str]]:
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("SELECT id, name FROM activities WHERE grp=? ORDER BY name", (grp,)).fetchall()
        return [(r[0], r[1]) for r in rows]

def get_activity_name(act_id: int) -> Optional[Tuple[str, str]]:
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute("SELECT name, grp FROM activities WHERE id=?", (act_id,)).fetchone()
        if not r:
            return None
        return (r[0], r[1])

def add_activity(grp: str, name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    with connect() as con, closing(con.cursor()) as c:
        try:
            c.execute("INSERT INTO activities(name, grp) VALUES(?,?)", (name, grp))
            con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def remove_activity(name: str) -> bool:
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM activities WHERE name=?", (name,))
        con.commit()
        return cur.rowcount > 0

def list_locations(grp: str) -> List[str]:
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("SELECT name FROM locations WHERE grp=? ORDER BY name", (grp,)).fetchall()
        return [r[0] for r in rows]

def list_locations_with_id(grp: str) -> List[Tuple[int, str]]:
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("SELECT id, name FROM locations WHERE grp=? ORDER BY name", (grp,)).fetchall()
        return [(r[0], r[1]) for r in rows]

def get_location_name(loc_id: int) -> Optional[Tuple[str, str]]:
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute("SELECT name, grp FROM locations WHERE id=?", (loc_id,)).fetchone()
        if not r:
            return None
        return (r[0], r[1])

def add_location(grp: str, name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    with connect() as con, closing(con.cursor()) as c:
        try:
            c.execute("INSERT INTO locations(name, grp) VALUES(?,?)", (name, grp))
            con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def remove_location(name: str) -> bool:
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM locations WHERE name=?", (name,))
        con.commit()
        return cur.rowcount > 0

def insert_report(user_id:str, reg_name:str, location:str, loc_grp:str,
                  activity:str, act_grp:str, work_date:str, hours:int) -> int:
    now = datetime.now().isoformat()
    with connect() as con, closing(con.cursor()) as c:
        c.execute("""
        INSERT INTO reports(created_at, user_id, reg_name, location, location_grp,
                            activity, activity_grp, work_date, hours)
        VALUES(?,?,?,?,?,?,?,?,?)
        """, (now, user_id, reg_name, location, loc_grp, activity, act_grp, work_date, hours))
        con.commit()
        report_id = c.lastrowid
    
    # Синхронизация с Google Sheets
    if GOOGLE_SHEETS_AVAILABLE:
        try:
            export_report_to_sheet(report_id)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось экспортировать отчет {report_id} в Google Sheets: {e}")
    
    return report_id

def get_report(report_id:int):
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute(
            "SELECT id, created_at, user_id, reg_name, location, location_grp, activity, activity_grp, work_date, hours FROM reports WHERE id=?",
            (report_id,)
        ).fetchone()
        if not r:
            return None
        return {
            "id": r[0], "created_at": r[1], "user_id": r[2], "reg_name": r[3],
            "location": r[4], "location_grp": r[5], "activity": r[6], "activity_grp": r[7],
            "work_date": r[8], "hours": r[9]
        }

def sum_hours_for_user_date(user_id:str, work_date:str, exclude_report_id: Optional[int] = None) -> int:
    with connect() as con, closing(con.cursor()) as c:
        if exclude_report_id:
            r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=? AND id<>?",
                          (user_id, work_date, exclude_report_id)).fetchone()
        else:
            r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=?",
                          (user_id, work_date)).fetchone()
        return int(r[0] or 0)

def user_recent_24h_reports(user_id:str) -> List[tuple]:
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("""
        SELECT id, work_date, activity, location, hours, created_at
        FROM reports
        WHERE user_id=? AND created_at>=?
        ORDER BY created_at DESC
        """, (user_id, cutoff)).fetchall()
        return rows

def delete_report(report_id:int, user_id:str) -> bool:
    # Сначала синхронизируем удаление с Google Sheets
    if GOOGLE_SHEETS_AVAILABLE:
        try:
            sync_report_delete(report_id)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось удалить отчет {report_id} из Google Sheets: {e}")
    
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM reports WHERE id=? AND user_id=?", (report_id, user_id))
        con.commit()
        return cur.rowcount > 0

def update_report_hours(report_id:int, user_id:str, new_hours:int) -> bool:
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("UPDATE reports SET hours=? WHERE id=? AND user_id=?", (new_hours, report_id, user_id))
        con.commit()
        success = cur.rowcount > 0
    
    # Синхронизация с Google Sheets
    if success and GOOGLE_SHEETS_AVAILABLE:
        try:
            sync_report_update(report_id)
        except Exception as e:
            logging.warning(f"⚠️ Не удалось обновить отчет {report_id} в Google Sheets: {e}")
    
    return success

def fetch_stats_range_for_user(user_id:str, start_date:str, end_date:str) -> List[tuple]:
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute("""
        SELECT work_date, location, activity, hours
        FROM reports
        WHERE user_id=? AND work_date>=? AND work_date<=?
        ORDER BY work_date DESC, created_at DESC
        """, (user_id, start_date, end_date)).fetchall()
        return rows

def is_admin(user_id: str) -> bool:
    return user_id in ADMIN_IDS

# Google Sheets функции
try:
    from google_sheets_manager import (
        initialize_google_sheets,
        export_reports_to_sheets,
        check_and_create_next_month_sheet,
        scheduled_export,
        export_report_to_sheet,
        sync_report_update,
        sync_report_delete
    )
    GOOGLE_SHEETS_AVAILABLE = True
    logging.info("✅ Google Sheets модуль загружен")
except ImportError as e:
    logging.warning(f"⚠️ Google Sheets модуль недоступен: {e}")
    GOOGLE_SHEETS_AVAILABLE = False
    
    # Stub функции если модуль недоступен
    def initialize_google_sheets():
        return False
    
    def export_reports_to_sheets():
        return 0, "Google Sheets не настроен"
    
    def check_and_create_next_month_sheet():
        return False, ""
    
    def scheduled_export():
        pass
    
    def export_report_to_sheet(report_id):
        return False
    
    def sync_report_update(report_id):
        return False
    
    def sync_report_delete(report_id):
        return False

# Инициализация Flask приложения
app = Flask(__name__)

# Инициализация 360dialog WhatsApp клиента
wa = WhatsApp360Client(
    api_key=WHATSAPP_TOKEN,
    base_url=WA_BASE_URL
)
logging.info("✅ Initialized 360dialog WhatsApp client")

@app.before_request
def log_request():
    if request.path == "/webhook" and request.method == "POST":
        logging.info(f"[DEBUG] Raw Webhook Payload: {request.get_data(as_text=True)}")

# -----------------------------
# Меню
# -----------------------------

def show_main_menu(wa: WhatsApp360Client, user_id: str, u: dict):
    name = (u or {}).get("full_name") or "—"
    buttons = [
        Button(title="🚜 Работа", callback_data="menu:work"),
        Button(title="📊 Статистика", callback_data="menu:stats"),
        Button(title="Ещё...", callback_data="menu:more"),
    ]
    text = f"👤 *{name}*\n\nВыберите действие:"
    wa.send_message(to=user_id, text=text, buttons=buttons)

def show_more_menu(wa: WhatsApp360Client, user_id: str):
    admin = is_admin(user_id)
    buttons = []
    
    if admin:
        # Для админа: Админ, Имя, Назад
        buttons.append(Button(title="⚙️ Админ", callback_data="menu:admin"))
        buttons.append(Button(title="✏️ Имя", callback_data="menu:name"))
    else:
        # Для обычного юзера: Перепись, Имя, Назад
        buttons.append(Button(title="📝 Перепись", callback_data="menu:edit"))
        buttons.append(Button(title="✏️ Имя", callback_data="menu:name"))
    
    buttons.append(Button(title="🔙 Назад", callback_data="menu:root"))
    
    wa.send_message(to=user_id, text="Доп. меню:", buttons=buttons[:3])

# -----------------------------
# Обработчики команд
# -----------------------------

def cmd_start(client: WhatsApp360Client, msg: MessageObject):
    init_db()
    user_id = msg.from_user.wa_id
    if not user_id:
        logging.warning("Received message without user_id")
        return
    
    upsert_user(user_id, None, TZ)
    u = get_user(user_id)
    
    if not u or not (u.get("full_name") or "").strip():
        set_state(user_id, "waiting_name")
        client.send_message(
            to=user_id,
            text="👋 Для начала введите *Фамилию Имя* (например: *Иванов Иван*)."
        )
        return
    
    show_main_menu(client, user_id, u)

def cmd_menu(client: WhatsApp360Client, msg: MessageObject):
    user_id = msg.from_user.wa_id
    if not user_id:
        logging.warning("Received message without user_id")
        return
    
    u = get_user(user_id)
    show_main_menu(client, user_id, u)

def cmd_today(client: WhatsApp360Client, msg: MessageObject):
    user_id = msg.from_user.wa_id
    if not user_id:
        logging.warning("Received message without user_id")
        return
    
    today = date.today().isoformat()
    rows = fetch_stats_range_for_user(user_id, today, today)
    if not rows:
        text = "📊 Сегодня у вас записей нет."
    else:
        parts = ["📊 *Сегодня*:"]
        total = 0
        for d, loc, act, h in rows:
            parts.append(f"• {loc} — {act}: *{h}* ч")
            total += h
        parts.append(f"\nИтого: *{total}* ч")
        text = "\n".join(parts)
    
    client.send_message(to=user_id, text=text)

def cmd_my(client: WhatsApp360Client, msg: MessageObject):
    user_id = msg.from_user.wa_id
    if not user_id:
        logging.warning("Received message without user_id")
        return
    
    end = date.today()
    start = end - timedelta(days=6)
    rows = fetch_stats_range_for_user(user_id, start.isoformat(), end.isoformat())
    if not rows:
        text = "📊 За 7 дней у вас записей нет."
    else:
        parts = [f"📊 *Неделя* ({start.strftime('%d.%m')}–{end.strftime('%d.%m')}):"]
        per_day = {}
        total = 0
        for d, loc, act, h in rows:
            per_day.setdefault(d, []).append((loc, act, h))
        for d in sorted(per_day.keys(), reverse=True):
            parts.append(f"\n*{d}*")
            for loc, act, h in per_day[d]:
                parts.append(f"• {loc} — {act}: *{h}* ч")
                total += h
        parts.append(f"\nИтого: *{total}* ч")
        text = "\n".join(parts)
    
    client.send_message(to=user_id, text=text)

# -----------------------------
# Обработка callback кнопок
# -----------------------------

@wa.on_callback_button
def handle_callback(client, btn: CallbackObject):
    user_id = btn.from_user.wa_id
    data = btn.data
    
    if data == "menu:root":
        u = get_user(user_id)
        clear_state(user_id)
        show_main_menu(client, user_id, u)
    
    elif data == "menu:more":
        show_more_menu(client, user_id)
    
    elif data == "menu:work":
        u = get_user(user_id)
        if not u or not (u.get("full_name") or "").strip():
            set_state(user_id, "waiting_name")
            client.send_message(to=user_id, text="Введите *Фамилию Имя* для регистрации.")
            return
        set_state(user_id, "pick_work_group", {})
        buttons = [
            Button(title="Техника", callback_data="work:grp:tech"),
            Button(title="Ручная", callback_data="work:grp:hand"),
            Button(title="🔙 Назад", callback_data="menu:root"),
        ]
        client.send_message(to=user_id, text="Выберите *тип работы*:", buttons=buttons)
    
    elif data == "menu:stats":
        admin = is_admin(user_id)
        buttons = [
            Button(title="Сегодня", callback_data="stats:today"),
            Button(title="Неделя", callback_data="stats:week"),
        ]
        
        # Add "Перепись" button for admins only
        if admin:
            buttons.append(Button(title="📝 Перепись", callback_data="menu:edit"))
        
        buttons.append(Button(title="🔙 Назад", callback_data="menu:root"))
        
        client.send_message(to=user_id, text="Выберите период статистики:", buttons=buttons)
    
    elif data == "menu:edit":
        rows = user_recent_24h_reports(user_id)
        if not rows:
            client.send_message(to=user_id, text="📝 За последние 24 часа записей нет.")
            return
        
        state = get_state(user_id)
        state["data"]["edit_records"] = rows
        set_state(user_id, "waiting_record_selection", state["data"])
        
        lines = ["Выберите *запись* для редактирования (отправьте номер):"]
        for i, r in enumerate(rows, 1):
            rid, wdate, act, loc, h, _ = r
            lines.append(f"{i}. {wdate} | {act} ({loc}) — *{h}ч*")
        lines.append("\n0. 🔙 Назад")
        
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)
    
    elif data == "menu:name":
        set_state(user_id, "waiting_name")
        client.send_message(to=user_id, text="✏️ Введите *Фамилию Имя* для изменения (например: *Иванов Иван*):")
    
    elif data == "menu:admin":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        buttons = [
            Button(title="➕➖ Работы", callback_data="adm:menu:activities"),
            Button(title="➕➖ Локации", callback_data="adm:menu:locations"),
            Button(title="📤 Экспорт", callback_data="adm:export"),
        ]
        client.send_message(to=user_id, text="⚙️ *Админ-панель*:", buttons=buttons)
    
    elif data == "adm:menu:activities":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        buttons = [
            Button(title="➕ Добавить работу", callback_data="adm:add:act"),
            Button(title="➖ Удалить работу", callback_data="adm:del:act"),
            Button(title="🔙 Админ", callback_data="menu:admin"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление работами*:", buttons=buttons)
    
    elif data == "adm:menu:locations":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        buttons = [
            Button(title="➕ Добавить локацию", callback_data="adm:add:loc"),
            Button(title="➖ Удалить локацию", callback_data="adm:del:loc"),
            Button(title="🔙 Админ", callback_data="menu:admin"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление локациями*:", buttons=buttons)
    
    elif data == "stats:today":
        cmd_today(client, btn)
    
    elif data == "stats:week":
        cmd_my(client, btn)
    
    elif data.startswith("work:grp:"):
        kind = data.split(":")[2]
        grp_name = GROUP_TECH if kind == "tech" else GROUP_HAND
        state = get_state(user_id)
        state["data"]["work"] = {"grp": grp_name}
        
        activities = list_activities_with_id(grp_name)
        state["data"]["acts"] = activities
        state["data"]["acts_kind"] = kind
        
        set_state(user_id, "waiting_activity_selection", state["data"])
        
        if not activities:
            client.send_message(to=user_id, text="❌ В этой категории нет работ.")
            return

        lines = ["Выберите *вид работы* (отправьте номер или название):"]
        for i, (aid, name) in enumerate(activities, 1):
            lines.append(f"{i}. {name}")
        lines.append(f"{len(activities) + 1}. 📝 Прочее (свой вариант)")
        lines.append("\n0. 🔙 Назад")
        
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)
    
    elif data.startswith("work:locgrp:"):
        lg = data.split(":")[2]
        grp = GROUP_FIELDS if lg == "fields" else GROUP_WARE
        state = get_state(user_id)
        work_data = state["data"].get("work", {})
        work_data["loc_grp"] = grp
        
        if lg == "ware":
            work_data["location"] = "Склад"
            state["data"]["work"] = work_data
            set_state(user_id, "pick_date", state["data"])
            
            today = date.today()
            dates = []
            lines = ["Выберите *дату* (отправьте номер):"]
            for i in range(7):
                d = today - timedelta(days=i)
                label = "Сегодня" if i == 0 else ("Вчера" if i == 1 else d.strftime("%d.%m"))
                dates.append(d.isoformat())
                lines.append(f"{i+1}. {label} ({d.strftime('%d.%m.%Y')})")
            lines.append("\n0. 🔙 Назад")
            
            state["data"]["dates_list"] = dates
            set_state(user_id, "waiting_date_selection", state["data"])
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text)
        else:
            state["data"]["work"] = work_data
            
            locations = list_locations_with_id(GROUP_FIELDS)
            state["data"]["locs"] = locations
            state["data"]["locs_group"] = lg
            
            set_state(user_id, "waiting_location_selection", state["data"])
            
            if not locations:
                client.send_message(to=user_id, text="❌ Локаций нет.")
                return

            lines = ["Выберите *место* (отправьте номер или название):"]
            for i, (lid, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            lines.append("\n0. 🔙 Назад")
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text)
    
    elif data.startswith("edit:del:"):
        try:
            rid = int(data.split(":")[2])
        except Exception:
            client.send_message(to=user_id, text="❌ Не удалось разобрать команду.")
            return

        ok = delete_report(rid, user_id)
        if ok:
            client.send_message(to=user_id, text="✅ Удалено")
        else:
            client.send_message(to=user_id, text="❌ Не получилось удалить")
        return
    
    elif data.startswith("edit:chg:"):
        try:
            _, _, rid, work_d = data.split(":", 3)
            rid = int(rid)
        except Exception:
            client.send_message(to=user_id, text="❌ Команда устарела или повреждена.")
            return
        
        state = get_state(user_id)
        state["data"]["edit_id"] = rid
        state["data"]["edit_date"] = work_d
        set_state(user_id, "waiting_edit_hours", state["data"])
        
        client.send_message(to=user_id, text=f"Введите *новое количество часов* для записи #{rid}:")
    
    elif data == "adm:add:act":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        buttons = [
            Button(title="🚜 Техника", callback_data="adm:add:act:tech"),
            Button(title="✋ Ручная", callback_data="adm:add:act:hand"),
            Button(title="🔙 Назад", callback_data="adm:menu:activities"),
        ]
        client.send_message(to=user_id, text="Выберите *группу работы*:", buttons=buttons)

    elif data == "adm:del:act":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        buttons = [
            Button(title="🚜 Техника", callback_data="adm:del:act:tech"),
            Button(title="✋ Ручная", callback_data="adm:del:act:hand"),
            Button(title="🔙 Назад", callback_data="adm:menu:activities"),
        ]
        client.send_message(to=user_id, text="Выберите *группу работы*:", buttons=buttons)

    elif data == "adm:add:loc":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        existing = list_locations(GROUP_FIELDS)
        lines = ["📋 *Существующие локации:*"]
        for i, name in enumerate(existing, 1):
            lines.append(f"{i}. {name}")
        lines.append("\n✏️ Введите название *новой локации*:")
        text = "\n".join(lines)
        set_state(user_id, "adm_wait_loc_add")
        client.send_message(to=user_id, text=text)

    elif data == "adm:del:loc":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        locations = list_locations_with_id(GROUP_FIELDS)
        if not locations:
            client.send_message(to=user_id, text="❌ Нет локаций для удаления.")
            return
        state = get_state(user_id)
        state["data"]["locs_del"] = locations
        set_state(user_id, "adm_wait_loc_del", state["data"])
        
        lines = ["Выберите *локацию* для удаления (отправьте номер или название):"]
        for i, (lid, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        lines.append("\n0. 🔙 Назад")
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)

    elif data.startswith("adm:add:act:"):
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        kind = data.split(":")[3]
        grp = GROUP_TECH if kind == "tech" else GROUP_HAND
        grp_label = "Техника" if kind == "tech" else "Ручная"
        
        existing = list_activities(grp)
        lines = [f"📋 *Существующие работы ({grp_label}):*"]
        for i, name in enumerate(existing, 1):
            lines.append(f"{i}. {name}")
        lines.append("\n✏️ Введите название *новой работы*:")
        text = "\n".join(lines)
        
        state = get_state(user_id)
        state["data"]["act_grp"] = grp
        set_state(user_id, "adm_wait_act_add", state["data"])
        client.send_message(to=user_id, text=text)
    
    elif data.startswith("adm:del:act:"):
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        kind = data.split(":")[3]
        grp = GROUP_TECH if kind == "tech" else GROUP_HAND
        grp_label = "Техника" if kind == "tech" else "Ручная"
        
        activities = list_activities_with_id(grp)
        if not activities:
            client.send_message(to=user_id, text=f"❌ Нет работ в группе '{grp_label}' для удаления.")
            return
        
        state = get_state(user_id)
        state["data"]["acts_del"] = activities
        state["data"]["act_grp"] = grp
        set_state(user_id, "adm_wait_act_del", state["data"])
        
        lines = [f"Выберите *работу* для удаления ({grp_label}) (отправьте номер или название):"]
        for i, (aid, name) in enumerate(activities, 1):
            lines.append(f"{i}. {name}")
        lines.append("\n0. 🔙 Назад")
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)
    
    elif data == "adm:export":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        client.send_message(to=user_id, text="⏳ Экспортирую отчеты в Google Sheets...")
        try:
            count, message = export_reports_to_sheets()
            text = f"✅ {message}" if count > 0 else f"ℹ️ {message}"
            created, sheet_msg = check_and_create_next_month_sheet()
            if created:
                text += f"\n\n📅 {sheet_msg}"
        except Exception as e:
            logging.error(f"Export error: {e}")
            text = f"❌ Ошибка экспорта: {str(e)}"
        
        client.send_message(to=user_id, text=text)
        
        # Возврат в главное меню
        u = get_user(user_id)
        show_main_menu(client, user_id, u)

# -----------------------------
# Обработка текстовых сообщений
# -----------------------------

@wa.on_message
def handle_text(client: WhatsApp360Client, msg: MessageObject):
    if not msg.from_user or not msg.from_user.wa_id:
        return

    user_id = msg.from_user.wa_id
    message_text = (msg.text or "").strip()
    norm_text = message_text.lower()
    logging.info(f"[TEXT] {user_id}: {message_text}")

    # 1. Обработка команд
    if norm_text in {"menu", "меню"}:
        cmd_menu(client, msg)
        return
    if norm_text in {"start", "старт"}:
        cmd_start(client, msg)
        return
    if norm_text in {"today", "сегодня"}:
        cmd_today(client, msg)
        return
    if norm_text in {"my", "мои"}:
        cmd_my(client, msg)
        return

    # 2. Обработка состояний (FSM)
    state = get_state(user_id)
    current_state = state.get("state")

    if current_state == "waiting_name":
        if len(message_text) < 3:
            client.send_message(to=user_id, text="❌ Слишком короткое имя. Введите Фамилию и Имя.")
            return
        
        upsert_user(user_id, message_text, TZ)
        clear_state(user_id)
        client.send_message(to=user_id, text=f"✅ Приятно познакомиться, {message_text}!")
        
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "waiting_activity_selection":
        if message_text == "0":
            buttons = [
                Button(title="Техника", callback_data="work:grp:tech"),
                Button(title="Ручная", callback_data="work:grp:hand"),
                Button(title="🔙 Назад", callback_data="menu:root"),
            ]
            client.send_message(to=user_id, text="Выберите *тип работы*:", buttons=buttons)
            clear_state(user_id)
            return

        acts = state["data"].get("acts", [])
        
        # Проверяем, выбрал ли пользователь "Прочее"
        if message_text.isdigit():
            choice_num = int(message_text)
            if choice_num == len(acts) + 1:
                # Пользователь выбрал "Прочее"
                set_state(user_id, "waiting_custom_activity_input", state["data"])
                client.send_message(
                    to=user_id, 
                    text="📝 Введите *название работы* (от 3 до 50 символов):\n\n0. 🔙 Назад"
                )
                return
        
        found = find_best_match(message_text, acts)
        if not found:
            client.send_message(to=user_id, text="❌ Не удалось распознать. Введите номер или название (или 0 для возврата).")
            return
        
        act_id, act_name = found
        
        res = get_activity_name(act_id)
        if not res:
            client.send_message(to=user_id, text="❌ Ошибка базы данных.")
            clear_state(user_id)
            return
            
        activity_name, grp_name = res
        
        work_data = state["data"].get("work", {})
        work_data["grp"] = grp_name
        work_data["activity"] = activity_name
        state["data"]["work"] = work_data
        set_state(user_id, "pick_loc_group", state["data"])
        
        buttons = [
            Button(title="Поля", callback_data="work:locgrp:fields"),
            Button(title="Склад", callback_data="work:locgrp:ware"),
            Button(title="🔙 Назад", callback_data="menu:work"),
        ]
        client.send_message(to=user_id, text=f"✅ Выбрано: *{activity_name}*\n\nТеперь выберите *локацию*:", buttons=buttons)
        return

    if current_state == "waiting_custom_activity_input":
        if message_text == "0":
            # Возврат к выбору работы
            work_data = state["data"].get("work", {})
            grp_name = work_data.get("grp", GROUP_TECH)
            
            activities = list_activities_with_id(grp_name)
            state["data"]["acts"] = activities
            set_state(user_id, "waiting_activity_selection", state["data"])
            
            lines = ["Выберите *вид работы* (отправьте номер или название):"]
            for i, (aid, name) in enumerate(activities, 1):
                lines.append(f"{i}. {name}")
            lines.append(f"{len(activities) + 1}. 📝 Прочее (свой вариант)")
            lines.append("\n0. 🔙 Назад")
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text)
            return
        
        # Валидация пользовательского ввода
        custom_activity = message_text.strip()
        if len(custom_activity) < 3:
            client.send_message(to=user_id, text="❌ Слишком короткое название. Минимум 3 символа.\n\n0. 🔙 Назад")
            return
        
        if len(custom_activity) > 50:
            client.send_message(to=user_id, text="❌ Слишком длинное название. Максимум 50 символов.\n\n0. 🔙 Назад")
            return
        
        # Сохраняем пользовательский ввод
        work_data = state["data"].get("work", {})
        grp_name = work_data.get("grp", GROUP_TECH)
        work_data["activity"] = custom_activity
        work_data["grp"] = grp_name
        state["data"]["work"] = work_data
        set_state(user_id, "pick_loc_group", state["data"])
        
        buttons = [
            Button(title="Поля", callback_data="work:locgrp:fields"),
            Button(title="Склад", callback_data="work:locgrp:ware"),
            Button(title="🔙 Назад", callback_data="menu:work"),
        ]
        client.send_message(to=user_id, text=f"✅ Выбрано: *{custom_activity}*\n\nТеперь выберите *локацию*:", buttons=buttons)
        return

    if current_state == "waiting_location_selection":
        if message_text == "0":
            buttons = [
                Button(title="Поля", callback_data="work:locgrp:fields"),
                Button(title="Склад", callback_data="work:locgrp:ware"),
                Button(title="🔙 Назад", callback_data="menu:work"),
            ]
            client.send_message(to=user_id, text="Выберите *локацию*:", buttons=buttons)
            return

        locs = state["data"].get("locs", [])
        found = find_best_match(message_text, locs)
        if not found:
            client.send_message(to=user_id, text="❌ Не удалось распознать. Введите номер или название (или 0 для возврата).")
            return
            
        loc_id, loc_name = found
        
        res = get_location_name(loc_id)
        if not res:
            client.send_message(to=user_id, text="❌ Ошибка базы данных.")
            clear_state(user_id)
            return
            
        location_name, grp = res
        
        work_data = state["data"].get("work", {})
        work_data["loc_grp"] = grp
        work_data["location"] = location_name
        state["data"]["work"] = work_data
        set_state(user_id, "pick_date", state["data"])
        
        today = date.today()
        dates = []
        lines = ["Выберите *дату* (отправьте номер):"]
        for i in range(7):
            d = today - timedelta(days=i)
            label = "Сегодня" if i == 0 else ("Вчера" if i == 1 else d.strftime("%d.%m"))
            dates.append(d.isoformat())
            lines.append(f"{i+1}. {label} ({d.strftime('%d.%m.%Y')})")
        lines.append("\n0. 🔙 Назад")
        
        state["data"]["dates_list"] = dates
        set_state(user_id, "waiting_date_selection", state["data"])
        
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)
        return

    if current_state == "waiting_date_selection":
        if message_text == "0":
            work_data = state["data"].get("work", {})
            lg = work_data.get("loc_grp")
            
            locations = list_locations_with_id(lg)
            state["data"]["locs"] = locations
            set_state(user_id, "waiting_location_selection", state["data"])
            
            lines = ["Выберите *место* (отправьте номер или название):"]
            for i, (lid, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            lines.append("\n0. 🔙 Назад")
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text)
            return

        dates = state["data"].get("dates_list", [])
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер даты из списка (1-7) или 0.")
            return
        
        idx = int(message_text) - 1
        if not (0 <= idx < len(dates)):
            client.send_message(to=user_id, text="❌ Неверный номер.")
            return
            
        selected_date = dates[idx]
        
        work_data = state["data"].get("work", {})
        work_data["work_date"] = selected_date
        state["data"]["work"] = work_data
        
        set_state(user_id, "waiting_hours_input", state["data"])
        client.send_message(to=user_id, text="Введите *количество часов* (от 1 до 24):\n0. 🔙 Назад")
        return

    if current_state == "waiting_hours_input":
        if message_text == "0":
            today = date.today()
            dates = []
            lines = ["Выберите *дату* (отправьте номер):"]
            for i in range(7):
                d = today - timedelta(days=i)
                label = "Сегодня" if i == 0 else ("Вчера" if i == 1 else d.strftime("%d.%m"))
                dates.append(d.isoformat())
                lines.append(f"{i+1}. {label} ({d.strftime('%d.%m.%Y')})")
            lines.append("\n0. 🔙 Назад")
            
            state["data"]["dates_list"] = dates
            set_state(user_id, "waiting_date_selection", state["data"])
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text)
            return

        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число (1-24) или 0.")
            return
        
        hours = int(message_text)
        if not (1 <= hours <= 24):
            client.send_message(to=user_id, text="❌ Часы должны быть от 1 до 24.")
            return
            
        work_data = state["data"].get("work", {})
        work_date = work_data.get("work_date")
        
        already = sum_hours_for_user_date(user_id, work_date)
        if already + hours > 24:
            max_can_add = 24 - already
            
            rows = fetch_stats_range_for_user(user_id, work_date, work_date)
            report_lines = []
            for _, loc, act, h in rows:
                report_lines.append(f"• {loc} — {act}: *{h}* ч")
            
            reports_text = "\n".join(report_lines) if report_lines else "Нет записей"
            
            error_msg = (
                f"❗ *Превышен лимит часов*\n\n"
                f"Уже записано на {work_date}: *{already}* ч\n"
                f"Вы хотите добавить: *{hours}* ч\n"
                f"Максимум: *24* ч\n"
                f"Можно добавить еще: *{max_can_add}* ч\n\n"
                f"📋 *Ваши записи за этот день:*\n{reports_text}\n\n"
                f"Пожалуйста, введите корректное количество часов (или 0 для возврата):"
            )
            client.send_message(to=user_id, text=error_msg)
            return

        u = get_user(user_id)
        rid = insert_report(
            user_id=user_id,
            reg_name=(u.get("full_name") or ""),
            location=work_data["location"],
            loc_grp=work_data["loc_grp"],
            activity=work_data["activity"],
            act_grp=work_data["grp"],
            work_date=work_data["work_date"],
            hours=hours
        )
        
        text = (
            f"✅ *Сохранено*\n\n"
            f"Дата: *{work_data['work_date']}*\n"
            f"Место: *{work_data['location']}*\n"
            f"Работа: *{work_data['activity']}*\n"
            f"Часы: *{hours}*\n"
            f"ID записи: `#{rid}`"
        )
        clear_state(user_id)
        client.send_message(to=user_id, text=text)
        show_main_menu(client, user_id, u)
        return

    if current_state == "waiting_record_selection":
        if message_text == "0":
            u = get_user(user_id)
            clear_state(user_id)
            show_main_menu(client, user_id, u)
            return

        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер записи из списка или 0.")
            return
        
        idx = int(message_text) - 1
        records = state["data"].get("edit_records", [])
        
        if not (0 <= idx < len(records)):
            client.send_message(to=user_id, text="❌ Неверный номер.")
            return
            
        r = records[idx]
        rid, wdate, act, loc, h, _ = r
        
        text = (
            f"📝 *Запись #{rid}*\n"
            f"Дата: {wdate}\n"
            f"Место: {loc}\n"
            f"Работа: {act}\n"
            f"Часы: *{h}*\n\n"
            f"Выберите действие:"
        )
        
        buttons = [
            Button(title="🖊 Править часы", callback_data=f"edit:chg:{rid}:{wdate}"),
            Button(title="🗑 Удалить", callback_data=f"edit:del:{rid}"),
            Button(title="🔙 Отмена", callback_data="menu:root"),
        ]
        client.send_message(to=user_id, text=text, buttons=buttons)
        return

    if current_state == "waiting_edit_hours":
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число (1-24).")
            return
        
        new_h = int(message_text)
        if not (1 <= new_h <= 24):
            client.send_message(to=user_id, text="❌ Часы должны быть от 1 до 24.")
            return
        
        try:
            rid = int(state["data"].get("edit_id"))
            work_d = state["data"].get("edit_date")
        except Exception:
            client.send_message(to=user_id, text="❌ Данные сессии устарели.")
            return
        
        already = sum_hours_for_user_date(user_id, work_d, exclude_report_id=rid)
        if already + new_h > 24:
            max_can_add = 24 - already
            error_msg = (
                f"❗ *Превышен лимит часов*\n\n"
                f"Сейчас учтено (без этой записи): *{already}* ч\n"
                f"Попытка установить: *{new_h}* ч\n"
                f"Максимум в сутки: *24* ч\n\n"
                f"Вы можете установить не более *{max_can_add}* ч."
            )
            client.send_message(to=user_id, text=error_msg)
            return
        
        ok = update_report_hours(rid, user_id, new_h)
        if ok:
            clear_state(user_id)
            client.send_message(to=user_id, text="✅ Обновлено")
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
        else:
            client.send_message(to=user_id, text="❌ Не получилось обновить")
        return

    if current_state == "adm_wait_act_add":
        grp = state["data"].get("act_grp", GROUP_TECH)
        if add_activity(grp, message_text):
            client.send_message(to=user_id, text=f"✅ Вид работы '{message_text}' добавлен.")
        else:
            client.send_message(to=user_id, text="❌ Ошибка или такой вид работ уже есть.")
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "adm_wait_act_del":
        if message_text == "0":
            buttons = [
                Button(title="🚜 Техника", callback_data="adm:del:act:tech"),
                Button(title="✋ Ручная", callback_data="adm:del:act:hand"),
                Button(title="🔙 Назад", callback_data="adm:menu:activities"),
            ]
            client.send_message(to=user_id, text="Выберите *группу работы*:", buttons=buttons)
            clear_state(user_id)
            return
        
        acts = state["data"].get("acts_del", [])
        found = find_best_match(message_text, acts)
        if not found:
            client.send_message(to=user_id, text="❌ Не удалось распознать. Введите номер или название (или 0 для возврата).")
            return
        
        act_id, act_name = found
        if remove_activity(act_name):
            client.send_message(to=user_id, text=f"✅ Вид работы '{act_name}' удален.")
        else:
            client.send_message(to=user_id, text="❌ Не найдено.")
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "adm_wait_loc_add":
        if add_location(GROUP_FIELDS, message_text):
            client.send_message(to=user_id, text=f"✅ Локация '{message_text}' добавлена.")
        else:
            client.send_message(to=user_id, text="❌ Ошибка или такая локация уже есть.")
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "adm_wait_loc_del":
        if message_text == "0":
            buttons = [
                Button(title="➕ Добавить локацию", callback_data="adm:add:loc"),
                Button(title="➖ Удалить локацию", callback_data="adm:del:loc"),
                Button(title="🔙 Админ", callback_data="menu:admin"),
            ]
            client.send_message(to=user_id, text="⚙️ *Управление локациями*:", buttons=buttons)
            clear_state(user_id)
            return
        
        locs = state["data"].get("locs_del", [])
        found = find_best_match(message_text, locs)
        if not found:
            client.send_message(to=user_id, text="❌ Не удалось распознать. Введите номер или название (или 0 для возврата).")
            return
        
        loc_id, loc_name = found
        if remove_location(loc_name):
            client.send_message(to=user_id, text=f"✅ Локация '{loc_name}' удалена.")
        else:
            client.send_message(to=user_id, text="❌ Не найдено.")
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    # 3. Если нет состояния и это не команда -> Показываем меню (если юзер зарегистрирован)
    u = get_user(user_id)
    if u and (u.get("full_name") or "").strip():
        show_main_menu(client, user_id, u)
    else:
        cmd_start(client, msg)

# -----------------------------
# Запуск
# -----------------------------

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Invalid verify token", 403
    
    wa.process_webhook(request.json)
    return "OK", 200

if __name__ == "__main__":
    init_db()
    
    # Инициализация Google Sheets
    if GOOGLE_SHEETS_AVAILABLE:
        logging.info("🔄 Инициализация Google Sheets...")
        if initialize_google_sheets():
            logging.info("✅ Google Sheets готов к работе")
        else:
            logging.warning("⚠️ Google Sheets не инициализирован, работа продолжится без синхронизации")
    
    if AUTO_EXPORT_ENABLED:
        scheduler = BackgroundScheduler(timezone=TZ)
        cron_parts = AUTO_EXPORT_CRON.split()
        if len(cron_parts) == 5:
            minute, hour, day, month, day_of_week = cron_parts
            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week
            )
            scheduler.add_job(scheduled_export, trigger)
            scheduler.start()
            logging.info(f"Scheduled export enabled: {AUTO_EXPORT_CRON}")
        else:
            logging.warning(f"Invalid cron expression: {AUTO_EXPORT_CRON}")
    
    logging.info("🤖 WhatsApp бот запущен!")
    logging.info("📡 Слушаю на %s:%s", SERVER_HOST, SERVER_PORT)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
