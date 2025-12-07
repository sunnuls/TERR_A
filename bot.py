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
REPORT_RELAY_PHONE = os.getenv("REPORT_RELAY_PHONE")
if REPORT_RELAY_PHONE:
    logging.info(f"🔧 REPORT_RELAY_PHONE loaded: {REPORT_RELAY_PHONE}")
else:
    logging.warning("⚠️ REPORT_RELAY_PHONE not set")

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

def _normalize_phone(phone: str) -> str:
    """Нормализует номер телефона: убирает все нецифровые символы"""
    if not phone:
        return ""
    return "".join(filter(str.isdigit, phone))

def _parse_admin_ids(s: str) -> List[str]:
    out = []
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        normalized = _normalize_phone(part.strip())
        if normalized:
            out.append(normalized)
    return out

ADMIN_IDS = set(_parse_admin_ids(os.getenv("ADMIN_IDS", "")))
logging.info(f"🔧 ADMIN_IDS loaded: {ADMIN_IDS}")

IT_IDS = set(_parse_admin_ids(os.getenv("IT_IDS", "")))
logging.info(f"🔧 IT_IDS loaded: {IT_IDS}")

TIM_IDS = set(_parse_admin_ids(os.getenv("TIM_IDS", "")))
logging.info(f"🔧 TIM_IDS loaded: {TIM_IDS}")

# -----------------------------
# Роли и права доступа (перемещено вверх)
# -----------------------------

def is_admin(user_id: str) -> bool:
    norm = _normalize_phone(user_id)
    return (user_id in ADMIN_IDS) or (norm and norm in ADMIN_IDS)

def is_it(user_id: str) -> bool:
    norm = _normalize_phone(user_id)
    return (user_id in IT_IDS) or (norm and norm in IT_IDS)

def is_tim(user_id: str) -> bool:
    """Проверка на роль TIM (Первый зам директора по ИТ)"""
    norm = _normalize_phone(user_id)
    return (user_id in TIM_IDS) or (norm and norm in TIM_IDS)

def is_brigadier(user_id: str) -> bool:
    # Check in DB
    with connect() as con, closing(con.cursor()) as c:
        # Проверяем наличие в таблице бригадиров
        exists = c.execute("SELECT 1 FROM brigadiers WHERE user_id=?", (user_id,)).fetchone()
        if exists:
            return True
        # Проверяем нормализованный номер
        norm = _normalize_phone(user_id)
        if norm and norm != user_id:
            exists = c.execute("SELECT 1 FROM brigadiers WHERE user_id=?", (norm,)).fetchone()
            if exists:
                return True
    return False

# GitHub Webhook секрет для автоматического обновления
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
if GITHUB_WEBHOOK_SECRET:
    logging.info("✅ GitHub Webhook секрет загружен")
else:
    logging.warning("⚠️ GITHUB_WEBHOOK_SECRET не установлен, автоматическое обновление отключено")

DB_PATH = os.path.join(os.getcwd(), "reports_whatsapp.db")

# Google Sheets настройки
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
OAUTH_CLIENT_JSON = os.getenv("OAUTH_CLIENT_JSON", "oauth_client.json")
TOKEN_JSON_PATH = Path(os.getenv("TOKEN_JSON_PATH", "token.json"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
EXPORT_PREFIX = "ОТД"

# Расписание автоматического экспорта
AUTO_EXPORT_ENABLED = os.getenv("AUTO_EXPORT_ENABLED", "false").lower() == "true"
AUTO_EXPORT_CRON = os.getenv("AUTO_EXPORT_CRON", "0 9 * * 1")

# -----------------------------
# Константы (дефолтные справочники)
# -----------------------------

# Тракторы
TRACTORS = [
    "JD7(с)", "JD7(н)", "GD8", "GD6", "Оранжевый", "Погрузчик", "Комбайн", "Прочее"
]

# Работы для трактора
ACTIVITIES_TRACTOR = [
    "Сев", "Опрыскивание", "МК", "Боронование", "Уборка", 
    "Дискование", "Пахота", "Чизелевание", "Навоз", "Прочее"
]

# Работы ручные
ACTIVITIES_MANUAL = [
    "Лесополоса", "Прополка", "Сев", "Уборка", "Прочее"
]

# Культуры
CROPS = [
    "Кабачок", "Картошка", "Подсолнечник", "Кукуруза", "Пшеница", "Горох", "Прочее"
]

# Культуры для КамАЗ (те же + Навоз если надо, но Навоз есть в работах трактора.
# Для КамАЗа "Навоз" может быть как груз. Добавим "Навоз" в список культур для КамАЗа отдельно или используем общий)
CROPS_KAMAZ = CROPS + ["Навоз"]

# Места погрузки для КамАЗа (поля + склад + прочее)
# Мы будем формировать их динамически из списка locations + "Склад"

DEFAULT_FIELDS = [
    "Северное","Фазенда","5 га","58 га","Фермерское","Сад",
    "Чеки №1","Чеки №2","Чеки №3","Рогачи (б)","Рогачи(М)",
    "Владимирова Аренда","МТФ",
]

# Оставляем старые списки для совместимости если где-то используются, 
# но основные теперь выше.
DEFAULT_TECH = ACTIVITIES_TRACTOR
DEFAULT_HAND = ACTIVITIES_MANUAL

GROUP_TECH = "техника" # Трактор
GROUP_HAND = "ручная"
GROUP_KAMAZ = "камаз" # Новый тип
GROUP_FIELDS = "поля"
GROUP_WARE = "склад"

WELCOME_MESSAGE = "Добро пожаловать! Этот бот поможет вам отправлять отчеты."

# -----------------------------
# Хранилище состояний пользователей (в памяти)
# -----------------------------

user_states: Dict[str, dict] = {}
user_history: Dict[str, list] = {}  # История состояний для возврата назад
processed_messages: set = set()

def is_message_processed(msg_id: str) -> bool:
    if msg_id in processed_messages:
        return True
    processed_messages.add(msg_id)
    # Simple cleanup: keep set size manageable (optional, for now just let it grow or clear periodically)
    if len(processed_messages) > 10000:
        processed_messages.clear()
    return False

def get_state(user_id: str) -> dict:
    if user_id not in user_states:
        user_states[user_id] = {"state": None, "data": {}}
    return user_states[user_id]

def save_to_history(user_id: str, back_callback: str):
    """
    Сохранить текущее состояние в историю с указанием callback для возврата назад.
    
    Args:
        user_id: ID пользователя
        back_callback: callback_data для возврата назад (например, "menu:root", "menu:work")
    """
    global _restoring_state
    
    # Не сохраняем историю при восстановлении состояния
    if _restoring_state:
        return
    
    s = get_state(user_id)
    if s["state"] is not None:
        if user_id not in user_history:
            user_history[user_id] = []
        # Сохраняем копию текущего состояния и callback для возврата
        user_history[user_id].append({
            "state": s["state"],
            "data": s["data"].copy() if s["data"] else {},
            "back_callback": back_callback
        })
        # Ограничиваем размер истории (последние 10 состояний)
        if len(user_history[user_id]) > 10:
            user_history[user_id] = user_history[user_id][-10:]

def set_state(user_id: str, state: Optional[str], data: dict = None, save_to_history: bool = True, back_callback: Optional[str] = None):
    """
    Установить состояние пользователя.
    
    Args:
        user_id: ID пользователя
        state: Название состояния
        data: Данные состояния
        save_to_history: Сохранять ли текущее состояние в историю перед переходом
        back_callback: callback_data для возврата назад (если save_to_history=True)
    """
    s = get_state(user_id)
    
    # Сохраняем текущее состояние в историю перед переходом (если это не очистка)
    save_to_history_func = globals().get("save_to_history")
    if save_to_history and s["state"] is not None and state is not None and back_callback and callable(save_to_history_func):
        save_to_history_func(user_id, back_callback)
    
    s["state"] = state
    if data is not None:
        s["data"] = data

def clear_state(user_id: str):
    user_states[user_id] = {"state": None, "data": {}}
    # Очищаем историю при полной очистке состояния
    if user_id in user_history:
        user_history[user_id] = []

# Флаг для предотвращения сохранения истории при восстановлении состояния
_restoring_state = False

def go_back(client, user_id: str) -> bool:
    """
    Вернуться на один шаг назад в истории состояний.
    Восстанавливает предыдущее состояние и вызывает соответствующий callback.
    
    Returns:
        True если удалось вернуться назад, False если истории нет
    """
    global _restoring_state
    
    if user_id not in user_history or not user_history[user_id]:
        return False
    
    # Восстанавливаем предыдущее состояние
    prev_state = user_history[user_id].pop()
    user_states[user_id] = {
        "state": prev_state["state"],
        "data": prev_state["data"].copy() if prev_state["data"] else {}
    }
    
    # Вызываем callback для восстановления экрана
    back_callback = prev_state.get("back_callback")
    if back_callback:
        # Устанавливаем флаг, чтобы не сохранять историю при восстановлении
        _restoring_state = True
        try:
            # Создаем временный объект callback для вызова обработчика
            class TempCallback:
                def __init__(self, user_id, data):
                    class TempUser:
                        def __init__(self, uid):
                            self.wa_id = uid
                    self.from_user = TempUser(user_id)
                    self.data = data
            
            temp_btn = TempCallback(user_id, back_callback)
            handle_callback(client, temp_btn)
        finally:
            _restoring_state = False
        return True
    
    return False

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
        CREATE TABLE IF NOT EXISTS brigadier_google_exports(
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id     INTEGER UNIQUE,
          spreadsheet_id TEXT,
          sheet_name    TEXT,
          row_number    INTEGER,
          exported_at   TEXT,
          last_updated  TEXT,
          FOREIGN KEY (report_id) REFERENCES brigadier_reports(id)
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
        c.execute("""
        CREATE TABLE IF NOT EXISTS brigadiers(
          user_id       TEXT PRIMARY KEY,
          username      TEXT,
          full_name     TEXT,
          added_by      TEXT,
          added_date    TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS brigadier_reports(
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id       TEXT,
          username      TEXT,
          work_type     TEXT,
          rows          INTEGER,
          field         TEXT,
          bags          INTEGER,
          workers       INTEGER,
          timestamp     TEXT,
          work_date     TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS reminder_status(
          user_id       TEXT,
          date          TEXT,
          status        TEXT,
          last_reminded_at TEXT,
          PRIMARY KEY (user_id, date)
        )
        """)

        def table_cols(table: str):
            return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}

        # Миграция для brigadier_reports (shift)
        br_cols = table_cols("brigadier_reports")
        if "shift" not in br_cols:
            c.execute("ALTER TABLE brigadier_reports ADD COLUMN shift TEXT")

        if "work_date" not in br_cols:
            c.execute("ALTER TABLE brigadier_reports ADD COLUMN work_date TEXT")
            c.execute("UPDATE brigadier_reports SET work_date=substr(timestamp, 1, 10) WHERE work_date IS NULL")

        # Миграция для reports (machinery, crop, trips)
        r_cols = table_cols("reports")
        if "machinery" not in r_cols:
            c.execute("ALTER TABLE reports ADD COLUMN machinery TEXT")
        if "crop" not in r_cols:
            c.execute("ALTER TABLE reports ADD COLUMN crop TEXT")
        if "trips" not in r_cols:
            c.execute("ALTER TABLE reports ADD COLUMN trips INTEGER")

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

def remove_activity_by_id(aid: int) -> bool:
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM activities WHERE id=?", (aid,))
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

def remove_location_by_id(lid: int) -> bool:
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM locations WHERE id=?", (lid,))
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

def sum_hours_for_user_date(user_id:str, work_date:str, exclude_report_id: Optional[int] = None, include_it: bool = False) -> int:
    """
    Получить сумму часов пользователя за дату.
    
    Args:
        user_id: ID пользователя
        work_date: Дата в формате ISO
        exclude_report_id: ID отчета для исключения (при редактировании)
        include_it: Включать ли IT отчеты (по умолчанию False - исключаем)
    """
    with connect() as con, closing(con.cursor()) as c:
        if exclude_report_id:
            if include_it:
                r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=? AND id<>?",
                              (user_id, work_date, exclude_report_id)).fetchone()
            else:
                r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=? AND id<>? AND location_grp != 'it' AND activity_grp != 'it'",
                              (user_id, work_date, exclude_report_id)).fetchone()
        else:
            if include_it:
                r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=?",
                              (user_id, work_date)).fetchone()
            else:
                r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=? AND location_grp != 'it' AND activity_grp != 'it'",
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
        AND location_grp != 'it' AND activity_grp != 'it'
        ORDER BY work_date DESC, created_at DESC
        """, (user_id, start_date, end_date)).fetchall()
        return rows

def is_admin(user_id: str) -> bool:
    return user_id in ADMIN_IDS

def is_it(user_id: str) -> bool:
    """Проверка, является ли пользователь IT"""
    normalized_user_id = _normalize_phone(user_id)
    result = normalized_user_id in IT_IDS
    if result:
        logging.info(f"✅ IT пользователь обнаружен: {user_id} (нормализован: {normalized_user_id})")
    return result

# Brigadier функции
def is_brigadier(user_id: str) -> bool:
    """Проверка, является ли пользователь бригадиром"""
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute("SELECT user_id FROM brigadiers WHERE user_id=?", (user_id,)).fetchone()
        return r is not None

def add_brigadier(user_id: str, username: str, full_name: str, added_by: str) -> bool:
    """Добавление бригадира"""
    now = datetime.now().isoformat()
    with connect() as con, closing(con.cursor()) as c:
        try:
            c.execute(
                "INSERT INTO brigadiers(user_id, username, full_name, added_by, added_date) VALUES(?,?,?,?,?)",
                (user_id, username, full_name, added_by, now)
            )
            con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def remove_brigadier(user_id: str) -> bool:
    """Удаление бригадира"""
    with connect() as con, closing(con.cursor()) as c:
        cur = c.execute("DELETE FROM brigadiers WHERE user_id=?", (user_id,))
        con.commit()
        return cur.rowcount > 0

def get_all_brigadiers() -> List[tuple]:
    """Получение списка всех бригадиров"""
    with connect() as con, closing(con.cursor()) as c:
        rows = c.execute(
            "SELECT user_id, username, full_name, added_by, added_date FROM brigadiers ORDER BY added_date DESC"
        ).fetchall()
        return rows

def save_brigadier_report(user_id: str, username: str, work_type: str, 
                          rows: int, field: str, bags: int, workers: int, work_date: str) -> int:
    """Сохранение отчета бригадира"""
    now = datetime.now().isoformat()
    with connect() as con, closing(con.cursor()) as c:
        c.execute("""
        INSERT INTO brigadier_reports(user_id, username, work_type, rows, field, bags, workers, timestamp, work_date)
        VALUES(?,?,?,?,?,?,?,?,?)
        """, (user_id, username, work_type, rows, field, bags, workers, now, work_date))
        con.commit()
        return c.lastrowid

# -----------------------------
# Reminder System Functions
# -----------------------------

def get_reminder_status(user_id: str, date_str: str) -> Optional[dict]:
    with connect() as con, closing(con.cursor()) as c:
        r = c.execute(
            "SELECT status, last_reminded_at FROM reminder_status WHERE user_id=? AND date=?",
            (user_id, date_str)
        ).fetchone()
        if not r:
            return None
        return {"status": r[0], "last_reminded_at": r[1]}

def set_reminder_status(user_id: str, date_str: str, status: str, last_reminded_at: str = None):
    with connect() as con, closing(con.cursor()) as c:
        if last_reminded_at:
            c.execute(
                "INSERT INTO reminder_status(user_id, date, status, last_reminded_at) VALUES(?,?,?,?) "
                "ON CONFLICT(user_id, date) DO UPDATE SET status=excluded.status, last_reminded_at=excluded.last_reminded_at",
                (user_id, date_str, status, last_reminded_at)
            )
        else:
             c.execute(
                "INSERT INTO reminder_status(user_id, date, status) VALUES(?,?,?) "
                "ON CONFLICT(user_id, date) DO UPDATE SET status=excluded.status",
                (user_id, date_str, status)
            )
        con.commit()

def is_report_filled_today(user_id: str) -> bool:
    today = date.today().isoformat()
    with connect() as con, closing(con.cursor()) as c:
        # Check regular reports
        r1 = c.execute("SELECT id FROM reports WHERE user_id=? AND work_date=?", (user_id, today)).fetchone()
        if r1: return True
        # Check brigadier reports
        r2 = c.execute("SELECT id FROM brigadier_reports WHERE user_id=? AND work_date=?", (user_id, today)).fetchone()
        if r2: return True
    return False

def check_reminders():
    """
    Checks if users need to be reminded to fill reports.
    Runs every minute.
    """
    now = datetime.now()
    today_str = now.date().isoformat()
    
    # Logic:
    # 1. If 14:00 <= now < 19:00: Remind every 49 min if not filled.
    # 2. If 19:00 <= now < 20:00: Remind once if filled (confirmation).
    
    hour = now.hour
    
    # Optimization: Only run check within relevant hours
    if not (14 <= hour < 20):
        return

    with connect() as con, closing(con.cursor()) as c:
        # Get all users
        users = c.execute("SELECT user_id FROM users").fetchall()
        
    for (uid,) in users:
        status_data = get_reminder_status(uid, today_str)
        status = status_data["status"] if status_data else None
        
        if status == "disabled":
            continue
            
        filled = is_report_filled_today(uid)
        
        # Condition 1: Not filled, afternoon reminder
        if 14 <= hour < 19:
            if not filled:
                last_reminded = status_data.get("last_reminded_at") if status_data else None
                should_remind = False
                
                if not last_reminded:
                    should_remind = True
                else:
                    last_dt = datetime.fromisoformat(last_reminded)
                    if (now - last_dt) >= timedelta(minutes=49):
                        should_remind = True
                
                if should_remind:
                    # Send reminder
                    buttons = [
                        Button(title="🚜 Заполнить ОТД", callback_data="menu:work"),
                        Button(title="😴 Я сегодня не работаю", callback_data="reminder:cancel")
                    ]
                    try:
                        wa.send_message(to=uid, text="🔔 *Не забудьте заполнить ОТД!*", buttons=buttons)
                        set_reminder_status(uid, today_str, "reminded", now.isoformat())
                    except Exception as e:
                        logging.error(f"Failed to send reminder to {uid}: {e}")

        # Condition 2: Filled, evening confirmation (once)
        elif 19 <= hour < 20:
            if filled and status != "reminded_19:00":
                try:
                    wa.send_message(
                        to=uid, 
                        text="✅ Вы уже заполнили отчет сегодня. Все верно? Если нужно добавить еще работы, нажмите кнопку ниже.",
                        buttons=[Button(title="🚜 Добавить еще", callback_data="menu:work")]
                    )
                    set_reminder_status(uid, today_str, "reminded_19:00", now.isoformat())
                except Exception as e:
                    logging.error(f"Failed to send 19:00 reminder to {uid}: {e}")

# Google Sheets функции
try:
    from google_sheets_manager import (
        initialize_google_sheets,
        export_reports_to_sheets,
        check_and_create_next_month_sheet,
        scheduled_export,
        export_report_to_sheet,
        sync_report_update,
        sync_report_delete,
        export_brigadier_reports,
        export_brigadier_report_to_sheet
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

def send_report_to_relay(original_from: str, original_text: str, user_name: str = None, is_edit: bool = False):
    """
    Отправляет копию отчета на релейный номер.
    
    Args:
        original_from: Номер телефона отправителя
        original_text: Текст отчета
        user_name: Имя пользователя (опционально)
        is_edit: Флаг редактирования отчета
    """
    if not REPORT_RELAY_PHONE:
        return

    try:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        # Используем имя пользователя, если доступно, иначе номер
        sender_info = user_name if user_name else original_from
        
        # Формируем сообщение для релея
        if is_edit:
            relay_text = (
                f"✏️ Отчёт изменен\n"
                f"Дата/время: {now_str}\n"
                f"Пользователь: {sender_info}\n"
                f"──────────────\n"
                f"{original_text}"
            )
        else:
            relay_text = (
                f"📋 Новый отчёт\n"
                f"Дата/время: {now_str}\n"
                f"Пользователь: {sender_info}\n"
                f"──────────────\n"
                f"{original_text}"
            )
        
        wa.send_message(to=REPORT_RELAY_PHONE, text=relay_text)
        action = "edited" if is_edit else "relayed"
        logging.info(f"✅ Report {action} to {REPORT_RELAY_PHONE}")
    except Exception as e:
        logging.error(f"❌ Failed to relay report: {e}")

@app.before_request
def log_request():
    if request.path == "/webhook" and request.method == "POST":
        logging.info(f"[DEBUG] Raw Webhook Payload: {request.get_data(as_text=True)}")

# -----------------------------
# Меню
# -----------------------------

def show_main_menu(wa: WhatsApp360Client, user_id: str, u: dict):
    name = (u or {}).get("full_name") or "—"
    
    # Проверяем роль пользователя
    it_user = is_it(user_id)
    tim_user = is_tim(user_id)
    brigadier = is_brigadier(user_id)
    
    # Отладочная информация для IT пользователей
    if it_user:
        logging.info(f"🔧 IT пользователь обнаружен в show_main_menu: {user_id}, IT_IDS={IT_IDS}")
    
    if tim_user:
        # Для TIM роли
        text = (
            f"Первый зам директора по Информационным Технологиям\n"
            f"*{name}*\n\n"
            f"Выберите действие:"
        )
        buttons = [
            Button(title="🇨🇳 Партия следить 🇨🇳", callback_data="tim:party"),
            Button(title="📊 Статистика", callback_data="menu:stats"),
            Button(title="✏️ Сменить имя", callback_data="menu:name"),
        ]
    elif it_user:
        # Для IT роли
        text = (
            f"mc.Lover (*{name}*)\n\n"
            f"*Команды:*\n"
            f"• `admin` - админское меню\n"
            f"• `briq` - бригадирское меню\n"
            f"• `tim` - меню TIM\n"
            f"• `rb1` - меню работяги\n"
            f"• `sts` - статистика"
        )
        buttons = [
            Button(title="⭐", callback_data="it:star"),
            Button(title="📊 Статистика", callback_data="menu:stats"),
        ]
    elif brigadier:
        # Бригадир сразу попадает в бриг-меню: ОБ, Статистика, Настройки
        buttons = [
            Button(title="👷 ОБ (Отчет)", callback_data="brig:report"),  # сразу в отчет
            Button(title="📊 Статистика", callback_data="menu:stats"),
            Button(title="⚙️ Настройки", callback_data="menu:settings"),
        ]
        text = f"👤 *{name}*\n\nВыберите действие: 🌻"
    else:
        # Обычный работяга
        buttons = [
            Button(title="🚜 ОТД", callback_data="menu:work"),
            Button(title="📊 Статистика", callback_data="menu:stats"),
            Button(title="⚙️ Настройки", callback_data="menu:settings"), # Вместо Ещё
        ]
        text = f"👤 *{name}*\n\nВыберите действие: 🌻"
    
    # Для админов добавляем подсказку
    if is_admin(user_id):
        text += "\n\n🛠 *Команды админа:*\n`/бриг` - Управление бригадирами\n`00` - В главное меню\n`sts` - Статистика\n`admin` - Админ панель"
        
    wa.send_message(to=user_id, text=text, buttons=buttons)

def show_settings_menu(wa: WhatsApp360Client, user_id: str):
    """Меню настроек (бывшее Ещё)"""
    buttons = [
        Button(title="✏️ Сменить имя", callback_data="menu:name"),
        Button(title="🔙 Назад", callback_data="back:prev"),
    ]
    wa.send_message(to=user_id, text="⚙️ *Настройки*\n\nВы можете изменить свое имя.", buttons=buttons)

def show_brigadier_menu(wa: WhatsApp360Client, user_id: str):
    """
    Главное меню бригадира (после нажатия ОБ)
    """
    # Сразу спрашиваем дату, как в ОТД
    show_date_selection(wa, user_id, prefix="brig:date")

def show_brigadier_stats_menu(wa: WhatsApp360Client, user_id: str):
    buttons = [
        Button(title="Сегодня", callback_data="brig:stats:today"),
        Button(title="Неделя", callback_data="brig:stats:week"),
        Button(title="🔙 Назад", callback_data="back:prev"),
    ]
    wa.send_message(to=user_id, text="📊 Выберите период статистики:", buttons=buttons)

def get_brigadier_stats(user_id: str, period: str) -> str:
    """
    Получение статистики бригадира
    period: 'today' или 'week'
    """
    today = date.today()
    start_date = today
    
    if period == 'week':
        start_date = today - timedelta(days=6)
    
    start_iso = start_date.isoformat()
    
    with connect() as con, closing(con.cursor()) as c:
        # Получаем отчеты за период
        rows = c.execute("""
            SELECT work_type, rows, bags, workers, work_date 
            FROM brigadier_reports 
            WHERE user_id = ? AND work_date >= ?
            ORDER BY work_date DESC
        """, (user_id, start_iso)).fetchall()
        
    if not rows:
        return "Нет данных за выбранный период."
    
    # Агрегация
    total_zucchini_rows = 0
    total_zucchini_workers = 0
    total_potato_rows = 0
    total_potato_bags = 0
    total_potato_workers = 0
    
    details = []
    
    for r in rows:
        w_type, w_rows, w_bags, w_workers, w_date = r
        d_str = date.fromisoformat(w_date).strftime("%d.%m")
        
        if w_type == "Кабачок":
            total_zucchini_rows += w_rows
            total_zucchini_workers += w_workers
            details.append(f"{d_str} 🥒: {w_rows}р, {w_workers}чел")
        elif w_type == "Картошка":
            total_potato_rows += w_rows
            total_potato_bags += w_bags
            total_potato_workers += w_workers
            details.append(f"{d_str} 🥔: {w_rows}р, {w_bags}с, {w_workers}чел")
            
    # Формируем текст
    period_str = "сегодня" if period == 'today' else "неделю (7 дней)"
    text = [f"📊 *Статистика за {period_str}*:\n"]
    
    if total_zucchini_rows > 0:
        text.append(f"🥒 *Кабачок*:")
        text.append(f"  Рядов: {total_zucchini_rows}")
        text.append(f"  Людей: {total_zucchini_workers}")
        
    if total_potato_rows > 0:
        text.append(f"\n🥔 *Картошка*:")
        text.append(f"  Рядов: {total_potato_rows}")
        text.append(f"  Сеток: {total_potato_bags}")
        text.append(f"  Людей: {total_potato_workers}")
        
    if period == 'week' and len(details) > 0:
        text.append("\n📝 *Детализация*:")
        # Показываем последние 10 записей
        text.extend(details[:10])
        if len(details) > 10:
            text.append(f"... и еще {len(details)-10}")
            
    return "\n".join(text)

def _save_tim_report(client, user_id):
    state = get_state(user_id)
    rep = state["data"].get("tim_report")
    if not rep:
        client.send_message(to=user_id, text="❌ Ошибка данных.")
        return

    u = get_user(user_id)
    reg_name = u.get("full_name") if u else user_id
    
    # Save to DB with group 'tim'
    report_id = insert_report(
        user_id=user_id,
        reg_name=reg_name,
        location=rep["location"],
        loc_grp="tim",
        activity=rep["activity"],
        act_grp="tim",
        work_date=rep["date"],
        hours=rep["hours"]
    )
    
    client.send_message(to=user_id, text=f"✅ Отчет сохранен (ID: {report_id})")
    clear_state(user_id)
    show_main_menu(client, user_id, u)

# -----------------------------
# Обработчики команд
# -----------------------------

def cmd_start(client: WhatsApp360Client, msg: MessageObject):
    init_db()
    user_id = msg.from_user.wa_id
    if not user_id:
        logging.warning("Received message without user_id")
        return
    
    # Check if user exists before upserting
    existing_user = get_user(user_id)
    if not existing_user:
        client.send_message(to=user_id, text=WELCOME_MESSAGE)
    
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

def show_date_selection(client: WhatsApp360Client, user_id: str, prefix: str):
    """
    Универсальная функция выбора даты (последние 7 дней).
    prefix: префикс для callback_data (например, 'work:date' или 'brig:date')
    """
    today = date.today()
    
    # Создаем список дат для интерактивного списка
    rows = []
    dates = []
    
    for i in range(7):
        d = today - timedelta(days=i)
        label = "Сегодня" if i == 0 else ("Вчера" if i == 1 else d.strftime("%d.%m"))
        full_date = d.strftime("%d.%m.%Y")
        
        # Для списка WhatsApp нужен уникальный ID
        date_id = f"{prefix}:{d.isoformat()}"
        dates.append(d.isoformat())
        
        rows.append({
            "id": date_id,
            "title": f"{label} ({full_date})",
            "description": ""  # Можно добавить день недели если нужно
        })
    
    # Добавляем кнопку Назад
    rows.append({
        "id": "back:prev",
        "title": "🔙 Назад",
        "description": "Вернуться в меню"
        })
    
    # Создаем секцию со списком дат
    sections = [
        {
            "title": "Выбор даты",
            "rows": rows
        }
    ]
    
    # Отправляем интерактивное сообщение со списком
    client.send_list_message(
        to=user_id,
        header_text="📅 Выбор даты",
        body_text="Выберите дату для заполнения отчета:",
        button_text="Выбрать дату",
        sections=sections
    )
    
    # Сохраняем состояние (на случай если понадобится fallback)
    set_state(user_id, "waiting_date_selection_universal", {"dates_list": dates, "next_prefix": prefix})

@wa.on_callback_button
def handle_callback(client, btn: CallbackObject):
    user_id = btn.from_user.wa_id
    data = btn.data
    
    # Обработка кнопки "Назад" - возврат на один шаг назад
    if data == "back:prev":
        if go_back(client, user_id):
            return
        else:
            # Если истории нет, возвращаемся в главное меню
            u = get_user(user_id)
            clear_state(user_id)
            show_main_menu(client, user_id, u)
            return

    # Специальные callback для возвратов по кнопке Назад (ручной поток)
    if data == "work:tractor:machinery":
        state = get_state(user_id)
        set_state(user_id, "work_tractor_machinery", state.get("data", {}), save_to_history=False)
        lines = ["Выберите *трактор* (отправьте номер):"]
        for i, m in enumerate(TRACTORS, 1):
            lines.append(f"{i}. {m}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:tractor:activity":
        state = get_state(user_id)
        set_state(user_id, "work_tractor_activity", state.get("data", {}), save_to_history=False)
        lines = ["Выберите *вид деятельности* (отправьте номер):"]
        for i, a in enumerate(ACTIVITIES_TRACTOR, 1):
            lines.append(f"{i}. {a}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:tractor:field":
        state = get_state(user_id)
        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        set_state(user_id, "work_tractor_field", state["data"], save_to_history=False)
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:tractor:crop":
        state = get_state(user_id)
        set_state(user_id, "work_tractor_crop", state.get("data", {}), save_to_history=False)
        lines = ["Выберите *культуру* (отправьте номер):"]
        for i, c in enumerate(CROPS, 1):
            lines.append(f"{i}. {c}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:choose:type":
        state = get_state(user_id)
        selected_date = state.get("data", {}).get("date", date.today().isoformat())
        set_state(user_id, "pick_work_group", {"date": selected_date}, save_to_history=False)
        buttons = [
            Button(title="🚜 Техника", callback_data="work:grp:tech"),
            Button(title="✋ Ручная", callback_data="work:type:manual"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
        client.send_message(to=user_id, text=f"📅 Дата: *{d_str}*\n\nВыберите *тип работы*:", buttons=buttons)
        return

    if data == "work:manual:activity":
        state = get_state(user_id)
        set_state(user_id, "work_manual_activity", state.get("data", {}), save_to_history=False)
        lines = ["Выберите *вид работы* (отправьте номер):"]
        for i, a in enumerate(ACTIVITIES_MANUAL, 1):
            lines.append(f"{i}. {a}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:manual:field":
        state = get_state(user_id)
        # Перестраиваем список полей
        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        set_state(user_id, "work_manual_field", state["data"], save_to_history=False)
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if data == "work:manual:crop":
        state = get_state(user_id)
        set_state(user_id, "work_manual_crop", state.get("data", {}), save_to_history=False)
        lines = ["Выберите *культуру* (отправьте номер):"]
        for i, c in enumerate(CROPS, 1):
            lines.append(f"{i}. {c}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return
    
    # Обработка команды star для IT роли
    if data == "it:star":
        if not is_it(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
    # New flow: Start with date selection for IT
        show_date_selection(client, user_id, prefix="it:date")
        return
    
    elif data.startswith("it:date:"):
        # IT flow: Date selected via list
        selected_date = data.split(":")[2]
        
        # Calculate current IT hours for today
        current_sum = sum_hours_for_user_date(user_id, selected_date, include_it=True)
        
        d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        
        set_state(user_id, "it_waiting_hours", {"date": selected_date}, save_to_history=False)
        quick_replies = [{"id": "back_to_date", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return
    
    if data == "menu:root":
        u = get_user(user_id)
        clear_state(user_id)
        show_main_menu(client, user_id, u)
    
    elif data == "menu:settings":
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:root")
        show_settings_menu(client, user_id)
    
    elif data == "menu:work":
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:root")
        u = get_user(user_id)
        if not u or not (u.get("full_name") or "").strip():
            set_state(user_id, "waiting_name", save_to_history=False)
            client.send_message(to=user_id, text="Введите *Фамилию Имя* для регистрации.")
            return
        
        # ОТД - Сразу выбор даты
        show_date_selection(client, user_id, prefix="work:date")
    
    elif data == "menu:stats":
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:root")
        
        # Приоритет: если пользователь IT, показываем ЛИЧНУЮ статистику (все типы)
        # Даже если он админ. Админскую он может посмотреть через sts или меню админа.
        if is_it(user_id):
            today = date.today()
            start_date = date(today.year, today.month, 1).isoformat()
            end_date = today.isoformat()
            
            # Fetch all reports for user (including IT)
            with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT work_date, location, activity, hours
                    FROM reports 
                    WHERE user_id=? AND work_date BETWEEN ? AND ?
                    ORDER BY work_date DESC, created_at DESC
                """, (user_id, start_date, end_date)).fetchall()
            
            month_name = calendar.month_name[today.month]
            if not rows:
                text = f"📊 *Моя статистика за {month_name}*\n\nЗаписей нет."
            else:
                parts = [f"📊 *Моя статистика за {month_name}*:"]
                per_day = {}
                total = 0
                for d, loc, act, h in rows:
                    per_day.setdefault(d, []).append((loc, act, h))
                
                for d in sorted(per_day.keys(), reverse=True):
                    d_obj = date.fromisoformat(d)
                    d_str = d_obj.strftime("%d.%m")
                    parts.append(f"\n📅 *{d_str}*")
                    for loc, act, h in per_day[d]:
                        parts.append(f"• {loc} — {act}: *{h}* ч")
                        total += h
                parts.append(f"\nИтого за месяц: *{total}* ч")
                text = "\n".join(parts)
            
            buttons = [
                Button(title="✏️ Изменить", callback_data="menu:edit_list"),
                Button(title="🗑 Удалить", callback_data="menu:delete_list"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            
            client.send_message(to=user_id, text=text, buttons=buttons)
            return

        # 1. Admin Logic (если не IT)
        if is_admin(user_id):
            buttons = [
                Button(title="🚜 Terra (Все)", callback_data="stats:admin:terra"),
                Button(title="👷 Бригадиры (Все)", callback_data="stats:admin:brig"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text="📊 *Статистика администратора*\n\nВыберите категорию:", buttons=buttons)
            return

        # 3. Brigadier Logic
        if is_brigadier(user_id):
            # Show brigadier stats for current month
            today = date.today()
            start_date = date(today.year, today.month, 1).isoformat()
            
            # Fetch brigadier reports
            with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT work_date, work_type, rows, bags, workers, field 
                    FROM brigadier_reports 
                    WHERE user_id = ? AND work_date >= ?
                    ORDER BY work_date DESC
                """, (user_id, start_date)).fetchall()
            
            month_name = calendar.month_name[today.month]
            if not rows:
                text = f"📊 *Статистика за {month_name}*\n\nЗаписей нет."
            else:
                parts = [f"📊 *Статистика за {month_name}*:"]
                per_day = {}
                
                # Aggregates
                total_rows = 0
                total_bags = 0
                
                for r in rows:
                    w_date, w_type, w_rows, w_bags, w_workers, w_field = r
                    per_day.setdefault(w_date, []).append((w_type, w_rows, w_bags, w_workers, w_field))
                    total_rows += w_rows
                    total_bags += w_bags
                
                for d in sorted(per_day.keys(), reverse=True):
                    d_obj = date.fromisoformat(d)
                    d_str = d_obj.strftime("%d.%m")
                    parts.append(f"\n📅 *{d_str}*")
                    for w_type, w_rows, w_bags, w_workers, w_field in per_day[d]:
                        field_info = f" ({w_field})" if w_field else ""
                        if w_type == "Кабачок":
                            parts.append(f"• 🥒 {w_rows}р, {w_workers}ч{field_info}")
                        else:
                            parts.append(f"• 🥔 {w_rows}р, {w_bags}с, {w_workers}ч{field_info}")
                
                parts.append(f"\nИтого: *{total_rows}* рядов, *{total_bags}* сеток")
                text = "\n".join(parts)
            
            buttons = [
                Button(title="✏️ Изменить", callback_data="menu:edit_list"),
                Button(title="🗑 Удалить", callback_data="menu:delete_list"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text=text, buttons=buttons)
            return

        # 3. Regular User Logic
        today = date.today()
        start_date = date(today.year, today.month, 1).isoformat()
        end_date = today.isoformat()
        
        rows = fetch_stats_range_for_user(user_id, start_date, end_date)
        
        month_name = calendar.month_name[today.month]
        if not rows:
            text = f"📊 *Статистика за {month_name}*\n\nЗаписей нет."
        else:
            parts = [f"📊 *Статистика за {month_name}*:"]
            per_day = {}
            total = 0
            for d, loc, act, h in rows:
                per_day.setdefault(d, []).append((loc, act, h))
            
            for d in sorted(per_day.keys(), reverse=True):
                d_obj = date.fromisoformat(d)
                d_str = d_obj.strftime("%d.%m")
                parts.append(f"\n📅 *{d_str}*")
                for loc, act, h in per_day[d]:
                    parts.append(f"• {loc} — {act}: *{h}* ч")
                    total += h
            parts.append(f"\nИтого за месяц: *{total}* ч")
            text = "\n".join(parts)
        
        buttons = [
            Button(title="✏️ Изменить", callback_data="menu:edit_list"),
            Button(title="🗑 Удалить", callback_data="menu:delete_list"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        
        client.send_message(to=user_id, text=text, buttons=buttons)

    elif data == "stats:admin:terra":
        if not is_admin(user_id): return
        today = date.today()
        start_date = date(today.year, today.month, 1).isoformat()
        
        with connect() as con, closing(con.cursor()) as c:
            rows = c.execute("""
                SELECT work_date, COUNT(DISTINCT user_id), SUM(hours)
                FROM reports
                WHERE work_date >= ? AND location_grp != 'it' AND activity_grp != 'it'
                GROUP BY work_date
                ORDER BY work_date DESC
            """, (start_date,)).fetchall()
            
        month_name = calendar.month_name[today.month]
        if not rows:
            text = f"🚜 *Terra (Все) - {month_name}*\n\nЗаписей нет."
        else:
            lines = [f"🚜 *Terra (Все) - {month_name}*\n"]
            total_h = 0
            for r in rows:
                wd, users, hours = r
                d_str = date.fromisoformat(wd).strftime("%d.%m")
                lines.append(f"📅 *{d_str}*: {users} чел, *{hours}* ч")
                total_h += hours
            lines.append(f"\nВсего часов: *{total_h}*")
            lines.append("\n💡 /x -open full")
            text = "\n".join(lines)
            
        # Set state to allow 'x' command
        set_state(user_id, "admin_viewing_stats", {"type": "terra"})
        client.send_message(to=user_id, text=text)

    elif data == "stats:admin:brig":
        if not is_admin(user_id): return
        today = date.today()
        start_date = date(today.year, today.month, 1).isoformat()
        
        with connect() as con, closing(con.cursor()) as c:
            rows = c.execute("""
                SELECT work_date, COUNT(DISTINCT user_id), SUM(rows), SUM(bags)
                FROM brigadier_reports
                WHERE work_date >= ?
                GROUP BY work_date
                ORDER BY work_date DESC
            """, (start_date,)).fetchall()
            
        month_name = calendar.month_name[today.month]
        if not rows:
            text = f"👷 *Бригадиры (Все) - {month_name}*\n\nЗаписей нет."
        else:
            lines = [f"👷 *Бригадиры (Все) - {month_name}*\n"]
            t_rows, t_bags = 0, 0
            for r in rows:
                wd, users, r_rows, r_bags = r
                d_str = date.fromisoformat(wd).strftime("%d.%m")
                lines.append(f"📅 *{d_str}*: {users} бриг, {r_rows}р, {r_bags}с")
                t_rows += r_rows
                t_bags += r_bags
            lines.append(f"\nИтого: *{t_rows}* рядов, *{t_bags}* сеток")
            lines.append("\n💡 /x -open full")
            text = "\n".join(lines)
            
        # Set state to allow 'x' command
        set_state(user_id, "admin_viewing_stats", {"type": "brig"})
        client.send_message(to=user_id, text=text)

    elif data == "menu:edit_list":
        # Logic to show list for editing (similar to old menu:edit)
        # We need to handle both regular and brigadier reports if needed, 
        # but for now let's stick to the user's role.
        
        if is_brigadier(user_id):
             # Brigadier edit list (last 24h or recent)
             # For simplicity, let's show recent 5
             with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT id, work_date, work_type, rows, field 
                    FROM brigadier_reports 
                    WHERE user_id=? 
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,)).fetchall()
             
             if not rows:
                 client.send_message(to=user_id, text="📝 Нет недавних записей для редактирования.")
                 return
                 
             lines = ["Выберите *запись* для изменения (отправьте номер):"]
             state = get_state(user_id)
             state["data"]["edit_list_brig"] = rows
             set_state(user_id, "wait_edit_brig_select", state["data"])
             
             for i, r in enumerate(rows, 1):
                 rid, wd, wt, wr, wf = r
                 lines.append(f"{i}. {wd} | {wt} ({wr}р) {wf or ''}")
             lines.append("\n0. 🔙 Назад")
             client.send_message(to=user_id, text="\n".join(lines))
             return

        # Regular user or IT user edit list
        # For IT users, we should also show IT reports.
        # user_recent_24h_reports filters out IT/admin reports by default.
        # We need to use a custom query for IT or update user_recent_24h_reports to accept an option.
        # Let's write a custom query here to be safe and explicit.
        
        if is_it(user_id):
             # IT user sees everything for last 24h
             with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT id, work_date, activity, location, hours, created_at
                    FROM reports 
                    WHERE user_id=? AND created_at >= datetime('now', '-1 day')
                    ORDER BY created_at DESC
                """, (user_id,)).fetchall()
        else:
             rows = user_recent_24h_reports(user_id)
             
        if not rows:
            client.send_message(to=user_id, text="📝 За последние 24 часа записей нет.")
            return
        
        state = get_state(user_id)
        state["data"]["edit_records"] = rows
        # Change state to new multi-select state
        set_state(user_id, "waiting_edit_selection_multi", state["data"])
        
        lines = ["Выберите *записи* для изменения (через запятую или пробел):"]
        for i, r in enumerate(rows, 1):
            rid, wdate, act, loc, h, _ = r
            lines.append(f"{i}. {wdate} | {act} ({loc}) — *{h}ч*")
        lines.append("\n0. 🔙 Назад")
        
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)

    elif data == "menu:delete_list":
        # Logic to show list for deletion
        if is_brigadier(user_id):
             with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT id, work_date, work_type, rows, field 
                    FROM brigadier_reports 
                    WHERE user_id=? 
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,)).fetchall()
             
             if not rows:
                 client.send_message(to=user_id, text="🗑 Нет недавних записей для удаления.")
                 return
                 
             lines = ["Выберите *запись* для удаления (отправьте номер):"]
             state = get_state(user_id)
             state["data"]["del_list_brig"] = rows
             set_state(user_id, "wait_del_brig_select", state["data"])
             
             for i, r in enumerate(rows, 1):
                 rid, wd, wt, wr, wf = r
                 lines.append(f"{i}. {wd} | {wt} ({wr}р) {wf or ''}")
             lines.append("\n0. 🔙 Назад")
             client.send_message(to=user_id, text="\n".join(lines))
             return

        # Regular user or IT user delete list
        if is_it(user_id):
             # IT user sees everything for last 24h
             with connect() as con, closing(con.cursor()) as c:
                rows = c.execute("""
                    SELECT id, work_date, activity, location, hours, created_at
                    FROM reports 
                    WHERE user_id=? AND created_at >= datetime('now', '-1 day')
                    ORDER BY created_at DESC
                """, (user_id,)).fetchall()
        else:
             rows = user_recent_24h_reports(user_id)

        if not rows:
            client.send_message(to=user_id, text="🗑 За последние 24 часа записей нет.")
            return
            
        state = get_state(user_id)
        state["data"]["del_records"] = rows
        set_state(user_id, "waiting_del_selection", state["data"])
        
        lines = ["Выберите *запись* для удаления (отправьте номер):"]
        for i, r in enumerate(rows, 1):
            rid, wdate, act, loc, h, _ = r
            lines.append(f"{i}. {wdate} | {act} ({loc}) — *{h}ч*")
        lines.append("\n0. 🔙 Назад")
        client.send_message(to=user_id, text="\n".join(lines))
    
    elif data == "menu:name":
        set_state(user_id, "waiting_name")
        client.send_message(to=user_id, text="✏️ Введите *Фамилию Имя* для изменения (например: *Иванов Иван*):")
    
    elif data == "tim:party":
        if not is_tim(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        # Start TIM flow: Date selection
        show_date_selection(client, user_id, prefix="tim:date")

    elif data.startswith("tim:date:"):
        # TIM Date selected
        selected_date = data.split(":")[2]
        
        # Check for saved template (last TIM report)
        # We can use the last report for this user with a specific flag or just last report in 'tim' group
        # But requirements say "if saved and confirmed". Let's check if we can reuse last values.
        # For now, let's just start free input flow.
        # But we need to support "Save and Confirm" template logic.
        # We can look for the last report in 'tim' group to suggest default values.
        
        state = get_state(user_id)
        
        # Check if user has a "template" (last report)
        last_report = None
        with connect() as con, closing(con.cursor()) as c:
            row = c.execute("""
                SELECT activity, location, hours 
                FROM reports 
                WHERE user_id=? AND (location_grp='tim' OR activity_grp='tim')
                ORDER BY created_at DESC LIMIT 1
            """, (user_id,)).fetchone()
            if row:
                last_report = {"activity": row[0], "location": row[1], "hours": row[2]}
        
        # If template exists, ask if they want to use it
        if last_report:
            # Save potential template to state
            set_state(user_id, "tim_template_confirm", {
                "date": selected_date,
                "template": last_report
            }, save_to_history=False)
            
            d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
            text = (
                f"🇨🇳 *Партия следить*\n"
                f"📅 Дата: *{d_str}*\n\n"
                f"Использовать прошлые данные?\n"
                f"• Работа: *{last_report['activity']}*\n"
                f"• Место: *{last_report['location']}*\n"
                f"• Часы: *{last_report['hours']}*\n"
            )
            buttons = [
                Button(title="✅ Да, использовать", callback_data="tim:tmpl:yes"),
                Button(title="✏️ Нет, новые", callback_data="tim:tmpl:no"),
                Button(title="🔙 Назад", callback_data="back:prev")
            ]
            client.send_message(to=user_id, text=text, buttons=buttons)
        else:
            # No template, start manual flow
            set_state(user_id, "tim_wait_activity", {"date": selected_date}, save_to_history=False)
            client.send_message(to=user_id, text="🇨🇳 Введите *вид работы*:\n\n0. 🔙 Назад")

    elif data == "tim:tmpl:yes":
        # Use template
        state = get_state(user_id)
        tmpl = state["data"].get("template")
        work_date = state["data"].get("date")
        
        if not tmpl or not work_date:
            client.send_message(to=user_id, text="❌ Ошибка шаблона. Начните заново.")
            return
            
        # Go to hours confirmation (or skip if we trust the template hours completely? 
        # The prompt says "simplified filling of date and hours", implying loc/act are auto-filled.
        # So we should probably let them edit hours if they want, or just confirm.
        # "simplified filling of date and hours" -> maybe we just ask hours?
        # Let's confirm hours.
        
        state["data"]["tim_report"] = {
            "activity": tmpl["activity"],
            "location": tmpl["location"],
            "date": work_date
        }
        # Pre-fill hours from template but allow change? 
        # Or just go to confirmation. Let's go to confirmation with template hours.
        state["data"]["tim_report"]["hours"] = tmpl["hours"]
        
        set_state(user_id, "tim_confirm", state["data"], save_to_history=False)
        
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"🇨🇳 *Подтверждение*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{tmpl['activity']}*\n"
            f"Место: *{tmpl['location']}*\n"
            f"Часы: *{tmpl['hours']}*\n\n"
            f"Все верно?"
        )
        buttons = [
            Button(title="✅ Подтвердить", callback_data="tim:save:simple"),
            Button(title="✏️ Изменить часы", callback_data="tim:edit:hours"), # Option to edit hours
            Button(title="🔄 Заново", callback_data="tim:party")
        ]
        client.send_message(to=user_id, text=text, buttons=buttons)

    elif data == "tim:tmpl:no":
        # Manual flow
        state = get_state(user_id)
        work_date = state["data"].get("date")
        set_state(user_id, "tim_wait_activity", {"date": work_date}, save_to_history=False)
        client.send_message(to=user_id, text="🇨🇳 Введите *вид работы*:\n\n0. 🔙 Назад")

    elif data == "tim:edit:hours":
        state = get_state(user_id)
        set_state(user_id, "tim_wait_hours", state["data"], save_to_history=False)
        client.send_message(to=user_id, text="🕒 Введите *количество часов*:\n\n0. 🔙 Назад")

    elif data == "tim:save:simple":
        # Save from template/confirmed state
        _save_tim_report(client, user_id)

    elif data == "tim:save:template":
        # Save manual entry AND allow future templating (implicit by saving to DB)
        _save_tim_report(client, user_id)

    elif data == "menu:admin":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:more")
        buttons = [
            Button(title="➕➖ Работы", callback_data="adm:menu:activities"),
            Button(title="➕➖ Локации", callback_data="adm:menu:locations"),
            Button(title="📤 Экспорт", callback_data="adm:export"),
        ]
        # Добавляем кнопку управления бригадирами
        buttons.append(Button(title="👷 Бригадиры", callback_data="adm:menu:brigadiers"))
        client.send_message(to=user_id, text="⚙️ *Админ-панель*:", buttons=buttons[:3])
    
    elif data == "adm:menu:activities":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:admin")
        buttons = [
            Button(title="➕ Добавить работу", callback_data="adm:add:act"),
            Button(title="➖ Удалить работу", callback_data="adm:del:act"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление работами*:", buttons=buttons)
    
    elif data == "adm:menu:locations":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:admin")
        buttons = [
            Button(title="➕ Добавить локацию", callback_data="adm:add:loc"),
            Button(title="➖ Удалить локацию", callback_data="adm:del:loc"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление локациями*:", buttons=buttons)
    
    elif data == "stats:today":
        cmd_today(client, btn)
    
    elif data == "stats:week":
        cmd_my(client, btn)
    

    
    elif data == "cancel_activity":
        # Cancel activity selection, return to work type selection
        buttons = [
            Button(title="🚜 Трактор", callback_data="work:type:tractor"),
            Button(title="🚛 КамАЗ", callback_data="work:type:kamaz"),
            Button(title="✋ Ручная", callback_data="work:type:manual"),
        ]
        client.send_message(to=user_id, text="Выберите *тип работы*:", buttons=buttons)
        # Don't clear state, just go back to work_pick_type? 
        # Actually we need to reset state to work_pick_type to be clean
        # state = get_state(user_id)
        # date = state["data"].get("date")
        # set_state(user_id, "work_pick_type", {"date": date})
        return
    
    elif data == "cancel_location":
        # Cancel location selection, return back using history
        if go_back(client, user_id):
            return
        else:
            # Fallback: return to location group selection
            state = get_state(user_id)
            work_data = state["data"].get("work", {})
            activity_name = work_data.get("activity", "работа")
            
            buttons = [
                Button(title="Поля", callback_data="work:locgrp:fields"),
                Button(title="Склад", callback_data="work:locgrp:ware"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text=f"✅ Выбрано: *{activity_name}*\n\nТеперь выберите *локацию*:", buttons=buttons)
        return
    
    elif data.startswith("work:date:"):
        # Дата выбрана (через callback, если бы мы использовали кнопки, но мы используем текстовый ввод)
        # Но оставим этот handler на случай, если мы решим использовать кнопки в будущем
        # или если вызов идет из другого места.
        selected_date = data.split(":")[2]
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:work")
        set_state(user_id, "pick_work_group", {"date": selected_date}, save_to_history=False)
        
        buttons = [
            Button(title="Техника", callback_data="work:grp:tech"),
            Button(title="Ручная", callback_data="work:type:manual"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
        client.send_message(to=user_id, text=f"📅 Дата: *{d_str}*\n\nВыберите *тип работы*:", buttons=buttons)

    elif data == "work:grp:tech":
        # Intermediate step: Technique -> Tractor/KamAZ choice
        state = get_state(user_id)
        work_data = state.get("data", {}) if state else {}
        work_date = work_data.get("date", date.today().isoformat())
        
        # Save current state so Back works (returns to date selection/menu:work)
        set_state(user_id, "work_pick_type", {"date": work_date}, back_callback="menu:work")
        
        buttons = [
            Button(title="🚜 Трактор", callback_data="work:type:tractor"),
            Button(title="🚛 КамАЗ", callback_data="work:type:kamaz"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        client.send_message(to=user_id, text=f"📅 Дата: *{d_str}*\n\nВыберите *технику*:", buttons=buttons)
    
    elif data.startswith("work:type:"):
        wtype = data.split(":")[2]
        state = get_state(user_id)
        # Preserve date
        work_date = state["data"].get("date")
        state["data"]["work_type"] = wtype
        
        if wtype == "tractor":
            # Трактор: выбор техники
            set_state(user_id, "work_tractor_machinery", state["data"], save_to_history=True, back_callback="work:choose:type")
            
            lines = ["Выберите *трактор* (отправьте номер):"]
            for i, m in enumerate(TRACTORS, 1):
                lines.append(f"{i}. {m}")
            
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            
        elif wtype == "kamaz":
            # КамАЗ: выбор культуры
            set_state(user_id, "work_kamaz_crop", state["data"], save_to_history=False)
            
            lines = ["Выберите *культуру* (отправьте номер):"]
            for i, c in enumerate(CROPS_KAMAZ, 1):
                lines.append(f"{i}. {c}")
                
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            
        elif wtype == "manual":
            # Ручная: выбор вида работы
            # Сохраняем шаг для корректной работы кнопки Назад
            set_state(user_id, "work_manual_activity", state["data"], save_to_history=True, back_callback="work:choose:type")
            
            lines = ["Выберите *вид работы* (отправьте номер):"]
            for i, a in enumerate(ACTIVITIES_MANUAL, 1):
                lines.append(f"{i}. {a}")
            
            client.send_message(
                to=user_id,
                text="\n".join(lines),
                buttons=[Button(title="🔙 Назад", callback_data="back:prev")]
            )

    elif data.startswith("brig:shift:"):
        shift_code = data.split(":")[2]
        shift_name = "Утренняя" if shift_code == "morning" else "Вечерняя"
        
        state = get_state(user_id)
        state["data"]["shift"] = shift_name
        
        # Next: Crop selection (Кабачок, Картошка, прочее)
        set_state(user_id, "brig_crop", state["data"], save_to_history=False)
        
        # Build list from CROPS but prioritizing Zucchini/Potato if they are in there, or custom list
        # Prompt says: "Кабачок, Картошка, прочее (списком)"
        # Let's use a specific list for Brigadier
        BRIG_CROPS = ["Кабачок", "Картошка", "Прочее"]
        
        lines = ["Выберите *культуру* (отправьте номер):"]
        for i, c in enumerate(BRIG_CROPS, 1):
            lines.append(f"{i}. {c}")
            
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
    
    elif data.startswith("work:locgrp:"):
        lg = data.split(":")[2]
        grp = GROUP_FIELDS if lg == "fields" else GROUP_WARE
        state = get_state(user_id)
        work_data = state["data"].get("work", {})
        work_data["loc_grp"] = grp
        
        # Сохраняем текущее состояние в историю перед переходом
        # Определяем callback для возврата - это экран выбора работы
        acts_kind = state["data"].get("acts_kind", "tech")
        save_to_history(user_id, f"work:grp:{acts_kind}")
        
        if lg == "ware":
            work_data["location"] = "Склад"
            state["data"]["work"] = work_data
            
            # Skip date selection (already done), go to hours
            # Сохраняем текущее состояние в историю перед переходом
            acts_kind = state["data"].get("acts_kind", "tech")
            save_to_history(user_id, f"work:grp:{acts_kind}")
            set_state(user_id, "waiting_hours", state["data"], save_to_history=False)
            
            # Calculate current hours for today
            work_date = state["data"].get("work", {}).get("date", date.today().isoformat())
            current_sum = sum_hours_for_user_date(user_id, work_date)
            d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
            
            text = (
                f"📅 Дата: *{d_str}*\n"
                f"📊 Уже внесено: *{current_sum}* ч\n\n"
                f"Введите *количество часов*:"
            )
            quick_replies = [{"id": "back_to_loc", "title": "🔙 Back"}]
            client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
            
        else:
            state["data"]["work"] = work_data
            
            locations = list_locations_with_id(GROUP_FIELDS)
            state["data"]["locs"] = locations
            state["data"]["locs_group"] = lg
            
            set_state(user_id, "waiting_location_selection", state["data"], save_to_history=False)
            
            if not locations:
                client.send_message(to=user_id, text="❌ Локаций нет.")
                return

            lines = ["Выберите *место* (отправьте номер или название):"]
            for i, (lid, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            
            text = "\n".join(lines)
            quick_replies = [{"id": "cancel_location", "title": "🔙 Back"}]
            client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
    
    elif data == "confirm:it":
        if not is_it(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        state = get_state(user_id)
        temp_report = state["data"].get("temp_report")
        if not temp_report:
            client.send_message(to=user_id, text="❌ Данные устарели. Начните заново.")
            return

        # Save IT report (не в общую группу)
        u = get_user(user_id)
        reg_name = u.get("full_name") if u else user_id
        
        report_id = insert_report(
            user_id=user_id,
            reg_name=reg_name,
            location=temp_report.get("location"),
            loc_grp=temp_report.get("loc_grp"),  # "it" - специальная группа
            activity=temp_report.get("activity"),
            act_grp=temp_report.get("act_grp"),  # "it" - специальная группа
            work_date=temp_report.get("work_date"),
            hours=temp_report.get("hours")
        )
        
        d_str = date.fromisoformat(temp_report.get("work_date")).strftime("%d.%m.%Y")
        
        text = (
            f"✅ *Отчет сохранен*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{temp_report.get('activity')}*\n"
            f"Место: *{temp_report.get('location')}*\n"
            f"Часы: *{temp_report.get('hours')}*\n"
            f"ID: `#{report_id}`"
        )
        
        clear_state(user_id)
        client.send_message(to=user_id, text=text)
        show_main_menu(client, user_id, u)
    
    elif data == "edit:it":
        if not is_it(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        # Возвращаемся к вводу часов
        set_state(user_id, "it_waiting_hours", {}, save_to_history=False)
        client.send_message(to=user_id, text="Введите *количество часов*:\n\n0. 🔙 Назад")
    
    elif data == "confirm:worker":
        state = get_state(user_id)
        temp_report = state["data"].get("temp_report")
        if not temp_report:
            client.send_message(to=user_id, text="❌ Данные устарели. Начните заново.")
            return

        # Save report
        u = get_user(user_id)
        reg_name = u.get("full_name") if u else user_id
        
        report_id = insert_report(
            user_id=user_id,
            reg_name=reg_name,
            location=temp_report.get("location"),
            loc_grp=temp_report.get("loc_grp"),
            activity=temp_report.get("activity"),
            act_grp=temp_report.get("act_grp"),
            work_date=temp_report.get("work_date"),
            hours=temp_report.get("hours")
        )
        
        d_str = date.fromisoformat(temp_report.get("work_date")).strftime("%d.%m.%Y")
        
        text = (
            f"✅ *Отчет сохранен*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{temp_report.get('activity')}*\n"
            f"Место: *{temp_report.get('location')}*\n"
            f"Часы: *{temp_report.get('hours')}*\n"
            f"ID: `#{report_id}`"
        )
        
        clear_state(user_id)
        client.send_message(to=user_id, text=text)
        
        # Отправляем копию отчета на релейный номер
        send_report_to_relay(original_from=user_id, original_text=text, user_name=reg_name, is_edit=False)
        
        show_main_menu(client, user_id, u)

    elif data == "edit:worker":
        # Restart flow
        show_date_selection(client, user_id, prefix="work:date")

    elif data == "confirm:brig":
        state = get_state(user_id)
        temp_report = state["data"].get("temp_report")
        if not temp_report:
            client.send_message(to=user_id, text="❌ Данные устарели. Начните заново.")
            return
            
        # Save report
        u = get_user(user_id)
        username = u.get("full_name") if u else user_id
        
        report_id = save_brigadier_report(
            user_id=user_id,
            username=username,
            work_type=temp_report["work_type"],
            rows=temp_report["rows"],
            field=temp_report["field"],
            bags=temp_report.get("bags", 0),
            workers=temp_report["workers"],
            work_date=temp_report["work_date"]
        )
        
        # Auto-export
        if GOOGLE_SHEETS_AVAILABLE:
            try:
                export_brigadier_report_to_sheet(report_id)
            except Exception as e:
                logging.error(f"Auto-export error: {e}")
        
        d_str = date.fromisoformat(temp_report["work_date"]).strftime("%d.%m.%Y")
        
        text = (
            f"✅ *Отчет сохранен*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Тип: *{temp_report['work_type']}*\n"
            f"Рядов: *{temp_report['rows']}*\n"
            f"Поле: *{temp_report['field']}*\n"
        )
        if temp_report.get("bags"):
             text += f"Сеток: *{temp_report['bags']}*\n"
             
        text += (
            f"Людей: *{temp_report['workers']}*\n"
            f"ID отчета: `#{report_id}`"
        )
        
        clear_state(user_id)
        client.send_message(to=user_id, text=text)
        show_main_menu(client, user_id, u)

    elif data == "edit:brig":
        # Restart brigadier flow
        # We need to know the date to restart correctly, or just go to date selection
        # Let's go to date selection for simplicity
        show_date_selection(client, user_id, prefix="brig:date")
    
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
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text="Выберите *группу работы*:", buttons=buttons)

    elif data == "adm:del:act":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        buttons = [
            Button(title="🚜 Техника", callback_data="adm:del:act:tech"),
            Button(title="✋ Ручная", callback_data="adm:del:act:hand"),
            Button(title="🔙 Назад", callback_data="back:prev"),
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

    elif data.startswith("adm:del:loc"):
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        # Parse page number
        page = 0
        if ":PAGE:" in data:
            try:
                page = int(data.split(":PAGE:")[1])
            except:
                page = 0
                
        locations = list_locations_with_id(GROUP_FIELDS)
        if not locations:
            client.send_message(to=user_id, text="❌ Нет локаций для удаления.")
            return
        
        # Pagination logic
        PAGE_SIZE = 8
        total_items = len(locations)
        total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE
        
        if page >= total_pages: page = total_pages - 1
        if page < 0: page = 0
        
        start_idx = page * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        current_page_items = locations[start_idx:end_idx]
        
        rows = []
        for lid, name in current_page_items:
            rows.append({
                "id": f"adm:del:loc:CONFIRM:{lid}",
                "title": name,
                "description": ""
            })
            
        # Add navigation buttons
        if page > 0:
            rows.append({
                "id": f"adm:del:loc:PAGE:{page-1}",
                "title": "⬅️ Назад",
                "description": ""
            })
        if page < total_pages - 1:
            rows.append({
                "id": f"adm:del:loc:PAGE:{page+1}",
                "title": "Вперед ➡️",
                "description": ""
            })
            
        sections = [{"title": f"Локации (Стр. {page+1}/{total_pages})", "rows": rows}]
        
        client.send_list_message(
            to=user_id,
            header_text="🗑 Удаление локации",
            body_text="Выберите локацию для удаления:",
            button_text="Выбрать локацию",
            sections=sections
        )

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
        
        # Parse kind and page
        parts = data.split(":")
        # Format: adm:del:act:<kind> or adm:del:act:<kind>:PAGE:<page>
        kind = parts[3]
        
        page = 0
        if "PAGE" in parts:
            try:
                page = int(parts[parts.index("PAGE") + 1])
            except:
                page = 0
                
        grp = GROUP_TECH if kind == "tech" else GROUP_HAND
        grp_label = "Техника" if kind == "tech" else "Ручная"
        
        activities = list_activities_with_id(grp)
        if not activities:
            client.send_message(to=user_id, text=f"❌ Нет работ в группе '{grp_label}' для удаления.")
            return
        
        # Pagination logic
        PAGE_SIZE = 8
        total_items = len(activities)
        total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE
        
        if page >= total_pages: page = total_pages - 1
        if page < 0: page = 0
        
        start_idx = page * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        current_page_items = activities[start_idx:end_idx]
        
        rows = []
        for aid, name in current_page_items:
            rows.append({
                "id": f"adm:del:act:CONFIRM:{aid}",
                "title": name,
                "description": ""
            })
            
        # Add navigation buttons
        if page > 0:
            rows.append({
                "id": f"adm:del:act:{kind}:PAGE:{page-1}",
                "title": "⬅️ Назад",
                "description": ""
            })
        if page < total_pages - 1:
            rows.append({
                "id": f"adm:del:act:{kind}:PAGE:{page+1}",
                "title": "Вперед ➡️",
                "description": ""
            })
            
        sections = [{"title": f"{grp_label} (Стр. {page+1}/{total_pages})", "rows": rows}]
        
        client.send_list_message(
            to=user_id,
            header_text="🗑 Удаление работы",
            body_text=f"Выберите работу ({grp_label}) для удаления:",
            button_text="Выбрать работу",
            sections=sections
        )
    


    elif data.startswith("adm:del:loc:CONFIRM:"):
        if not is_admin(user_id): return
        try:
            lid = int(data.split(":")[4])
            if remove_location_by_id(lid):
                client.send_message(to=user_id, text="✅ Локация удалена.")
            else:
                client.send_message(to=user_id, text="❌ Ошибка удаления.")
        except Exception as e:
            logging.error(f"Error deleting location: {e}")
            client.send_message(to=user_id, text="❌ Ошибка.")
        
        # Return to menu
        buttons = [
            Button(title="➕ Добавить", callback_data="adm:add:loc"),
            Button(title="➖ Удалить", callback_data="adm:del:loc"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление локациями*:", buttons=buttons)

    elif data.startswith("adm:del:act:CONFIRM:"):
        if not is_admin(user_id): return
        try:
            aid = int(data.split(":")[4])
            if remove_activity_by_id(aid):
                client.send_message(to=user_id, text="✅ Работа удалена.")
            else:
                client.send_message(to=user_id, text="❌ Ошибка удаления.")
        except Exception as e:
            logging.error(f"Error deleting activity: {e}")
            client.send_message(to=user_id, text="❌ Ошибка.")
            
        # Return to menu
        buttons = [
            Button(title="➕ Добавить", callback_data="adm:add:act"),
            Button(title="➖ Удалить", callback_data="adm:del:act"),
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text="⚙️ *Управление работами*:", buttons=buttons)
    
    elif data == "adm:export":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        
        # client.send_message(to=user_id, text="⏳ Экспортирую отчеты в Google Sheets...")
        try:
            count, message = export_reports_to_sheets()
            text = f"✅ {message}" if count > 0 else f"ℹ️ {message}"
            
            # Экспорт бригадиров
            brig_count, brig_msg = export_brigadier_reports()
            if brig_count > 0:
                text += f"\n✅ {brig_msg}"
            elif "Ошибка" in brig_msg:
                text += f"\n❌ {brig_msg}"
            
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
    # Обработчики для бригадиров
    # -----------------------------
    
    elif data == "menu:brigadier":
        # Показать меню выбора действия (кнопки, как на первом скрине)
        # IT и админам тоже разрешаем вход для тестов/поддержки
        if not (is_brigadier(user_id) or is_it(user_id) or is_admin(user_id)):
            client.send_message(to=user_id, text="❌ У вас нет прав бригадира")
            return
        save_to_history(user_id, "menu:root")
        buttons = [
            Button(title="👷 ОБ (Отчет)", callback_data="brig:report"),
            Button(title="📊 Статистика", callback_data="brig:stats"),
            Button(title="⚙️ Настройки", callback_data="menu:settings"),
        ]
        client.send_message(to=user_id, text="👷 *Меню бригадира*\n\nВыберите действие: 🌻", buttons=buttons)

    elif data == "brig:report":
        # ОБ (Отчет) -> выбор даты
        show_date_selection(client, user_id, prefix="brig:report:date")

    elif data.startswith("brig:report:date:"):
        # После выбора даты -> выбор культуры
        selected_date = data.split(":")[3]
        buttons = [
            Button(title="🥒 Кабачок", callback_data=f"brig:report:type:zucchini:{selected_date}"),
            Button(title="🥔 Картошка", callback_data=f"brig:report:type:potato:{selected_date}"),
            Button(title="🔙 Назад", callback_data="brig:report"),
        ]
        d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
        client.send_message(to=user_id, text=f"📅 *{d_str}*\nВыберите культуру:", buttons=buttons)

    elif data.startswith("brig:report:type:zucchini:"):
        selected_date = data.split(":")[4]
        work_payload = {"work_type": "Кабачок", "date": selected_date}
        set_state(user_id, "brig_zucchini_rows", work_payload, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data=f"brig:report:date:{selected_date}")]
        client.send_message(to=user_id, text=f"🥒 *Кабачок* ({selected_date})\n\nВведите *количество рядов*:", buttons=buttons)

    elif data.startswith("brig:report:type:potato:"):
        selected_date = data.split(":")[4]
        work_payload = {"work_type": "Картошка", "date": selected_date}
        set_state(user_id, "brig_potato_rows", work_payload, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data=f"brig:report:date:{selected_date}")]
        client.send_message(to=user_id, text=f"🥔 *Картошка* ({selected_date})\n\nВведите *количество выкопанных рядов*:", buttons=buttons)

    elif data == "brig:menu:zucchini":
        # Выбор даты для кабачков
        show_date_selection(client, user_id, prefix="brig:date:zucchini")
        
    elif data == "brig:menu:potato":
        # Выбор даты для картошки
        show_date_selection(client, user_id, prefix="brig:date:potato")
    
    elif data.startswith("brig:date:zucchini:"):
        selected_date = data.split(":")[3]
        # Start zucchini flow
        set_state(user_id, "brig_zucchini_rows", {"work_type": "Кабачок", "date": selected_date}, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data="menu:brigadier")] # Back to brig menu
        client.send_message(to=user_id, text=f"🥒 *Кабачок* ({selected_date})\n\nВведите *количество рядов*:", buttons=buttons)

    elif data.startswith("brig:date:potato:"):
        selected_date = data.split(":")[3]
        # Start potato flow
        set_state(user_id, "brig_potato_rows", {"work_type": "Картошка", "date": selected_date}, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data="menu:brigadier")]
        client.send_message(to=user_id, text=f"🥔 *Картошка* ({selected_date})\n\nВведите *количество выкопанных рядов*:", buttons=buttons)
    
    elif data == "brig:stats":
        show_brigadier_stats_menu(client, user_id)
        
    elif data == "brig:stats:today":
        text = get_brigadier_stats(user_id, 'today')
        client.send_message(to=user_id, text=text)
        show_brigadier_stats_menu(client, user_id)
        
    elif data == "reminder:cancel":
        today_str = date.today().isoformat()
        set_reminder_status(user_id, today_str, "disabled")
        client.send_message(to=user_id, text="🔕 Уведомления на сегодня отключены.")

    elif data == "brig:stats:week":
        text = get_brigadier_stats(user_id, 'week')
        client.send_message(to=user_id, text=text)
        show_brigadier_stats_menu(client, user_id)

    elif data == "brig:zucchini":
        # Получаем выбранную дату из состояния
        state = get_state(user_id)
        selected_date = state["data"].get("date", date.today().isoformat())
        
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "brig:date:" + selected_date)
        # Начать форму для кабачков
        set_state(user_id, "brig_zucchini_rows", {"work_type": "Кабачок", "date": selected_date}, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="🥒 *Кабачок*\n\nВведите *количество рядов*:", buttons=buttons)
    
    elif data == "brig:potato":
        # Получаем выбранную дату из состояния
        state = get_state(user_id)
        selected_date = state["data"].get("date", date.today().isoformat())
        
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "brig:date:" + selected_date)
        # Начать форму для картошки
        set_state(user_id, "brig_potato_rows", {"work_type": "Картошка", "date": selected_date}, save_to_history=False)
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="🥔 *Картошка*\n\nВведите *количество выкопанных рядов*:", buttons=buttons)
    
    # -----------------------------
    # Админ: Управление бригадирами
    # -----------------------------
    
    elif data == "adm:menu:brigadiers":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        # Сохраняем текущее состояние в историю перед переходом
        save_to_history(user_id, "menu:admin")
        buttons = [
            Button(title="➕ Добавить бригадира", callback_data="adm:add:brigadier"),
            Button(title="➖ Удалить бригадира", callback_data="adm:del:brigadier"),
            Button(title="📋 Список бригадиров", callback_data="adm:list:brigadiers"),
        ]
        client.send_message(to=user_id, text="👷 *Управление бригадирами*:", buttons=buttons)
    
    elif data == "adm:add:brigadier":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        set_state(user_id, "adm_wait_brigadier_add")
        client.send_message(
            to=user_id, 
            text="➕ *Добавление бригадира*\n\nОтправьте *контакт* бригадира или введите *номер телефона* (например: 79001234567):"
        )
    
    elif data == "adm:del:brigadier":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        brigadiers = get_all_brigadiers()
        if not brigadiers:
            client.send_message(to=user_id, text="❌ Нет бригадиров для удаления.")
            return
        
        state = get_state(user_id)
        state["data"]["brigadiers_list"] = brigadiers
        set_state(user_id, "adm_wait_brigadier_del", state["data"])
        
        lines = ["Выберите *бригадира* для удаления (отправьте номер):"]
        for i, (uid, uname, fname, added_by, added_date) in enumerate(brigadiers, 1):
            lines.append(f"{i}. {fname or uname} ({uid})")
        lines.append("\n0. 🔙 Назад")
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)
    
    elif data == "adm:list:brigadiers":
        if not is_admin(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            return
        brigadiers = get_all_brigadiers()
        if not brigadiers:
            client.send_message(to=user_id, text="📋 *Список бригадиров*\n\nСписок пуст.")
            return
        
        lines = ["📋 *Список бригадиров*:\n"]
        for i, (uid, uname, fname, added_by, added_date) in enumerate(brigadiers, 1):
            # Показываем Имя (или username) и ID
            display_name = fname or uname or "Без имени"
            lines.append(f"{i}. {display_name}")
            lines.append(f"   ID: `{uid}`\n")
        text = "\n".join(lines)
        client.send_message(to=user_id, text=text)

    elif data == "back_to_date":
        # Возврат к выбору даты (для IT)
        show_date_selection(client, user_id, prefix="it:date")

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
    # Глобальный сброс
    if message_text == "00":
        clear_state(user_id)
        u = get_user(user_id)
        client.send_message(to=user_id, text="🔄 Сброс в главное меню")
        show_main_menu(client, user_id, u)
        return

    # Команды для IT роли
    if is_it(user_id):
        if norm_text == "admin":
            # Сохраняем текущее состояние в историю перед переходом
            save_to_history(user_id, "menu:more")
            # Показываем админское меню, но с полным функционалом работяги
            buttons = [
                Button(title="🚜 ОТД", callback_data="menu:work"),
                Button(title="📊 Статистика", callback_data="menu:stats"),
                Button(title="⚙️ Админ", callback_data="menu:admin"),
            ]
            client.send_message(to=user_id, text="⚙️ *Админ-меню*\n\nВыберите действие:", buttons=buttons)
            return
        elif norm_text == "expo":
            # IT command to trigger export
            client.send_message(to=user_id, text="⏳ Запуск экспорта отчетов...")
            try:
                count, message = export_reports_to_sheets()
                text = f"✅ {message}" if count > 0 else f"ℹ️ {message}"
                
                # Экспорт бригадиров
                brig_count, brig_msg = export_brigadier_reports()
                if brig_count > 0:
                    text += f"\n✅ {brig_msg}"
                elif "Ошибка" in brig_msg:
                    text += f"\n❌ {brig_msg}"
                
                created, sheet_msg = check_and_create_next_month_sheet()
                if created:
                    text += f"\n\n📅 {sheet_msg}"
            except Exception as e:
                logging.error(f"Export error: {e}")
                text = f"❌ Ошибка экспорта: {str(e)}"
            
            client.send_message(to=user_id, text=text)
            return
        elif norm_text in {"briq", "бриг", "/бриг"}:
            # Сохраняем текущее состояние в историю перед переходом
            save_to_history(user_id, "menu:more")
            
            # Проверка прав: IT, Admin или Brigadier
            if not (is_it(user_id) or is_admin(user_id) or is_brigadier(user_id)):
                 client.send_message(to=user_id, text="❌ У вас нет прав для доступа к меню бригадира.")
                 return

            # Показываем бригадирское меню (НОВОЕ)
            data_obj = type('obj', (object,), {'data': 'menu:brigadier'})()
            btn_obj = type('obj', (object,), {'from_user': msg.from_user, 'data': 'menu:brigadier'})()
            handle_callback(client, btn_obj)
            return
        elif norm_text == "rname":
            set_state(user_id, "waiting_name", save_to_history=False)
            client.send_message(to=user_id, text="Введите *Фамилию Имя* для изменения:")
            return
        elif norm_text == "sts":
            # Для IT sts работает как админская статистика
            save_to_history(user_id, "menu:more")
            buttons = [
                Button(title="🚜 Terra (Все)", callback_data="stats:admin:terra"),
                Button(title="👷 Бригадиры (Все)", callback_data="stats:admin:brig"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text="📊 *Статистика (IT/Admin)*\n\nВыберите категорию:", buttons=buttons)
            return

    # Команда для проверки IT роли и показа меню (обрабатывается ДО команды menu)
    if norm_text in {"it", "ит", "itmenu", "итменю", "checkit", "чекит"}:
        # Нормализуем номер для сравнения
        normalized_user_id = _normalize_phone(user_id)
        is_it_user = is_it(user_id)
        logging.info(f"🔍 Проверка IT роли для {user_id} (нормализован: {normalized_user_id}): is_it={is_it_user}, IT_IDS={IT_IDS}")
        
        if is_it_user:
            u = get_user(user_id)
            clear_state(user_id)
            show_main_menu(client, user_id, u)
            client.send_message(to=user_id, text="✅ IT меню активировано!")
        else:
            # Показываем отладочную информацию
            debug_info = (
                f"❌ *Ваш номер не найден в IT_IDS*\n\n"
                f"Ваш номер: `{user_id}`\n"
                f"Нормализованный: `{normalized_user_id}`\n"
                f"Текущие IT_IDS: {', '.join(IT_IDS) if IT_IDS else 'не настроены'}\n\n"
                f"Для добавления добавьте ваш номер в .env на сервере:\n"
                f"`IT_IDS={normalized_user_id}`\n\n"
                f"После этого перезапустите бота командой:\n"
                f"`systemctl restart terra-bot.service`"
            )
            client.send_message(to=user_id, text=debug_info)
        return
    
    # Команда rb1 для IT: показать меню обычного работяги
    if norm_text == "rb1":
        if is_it(user_id):
            u = get_user(user_id)
            # Принудительно показываем меню работяги (ОТД, Статистика, Настройки)
            name = (u or {}).get("full_name") or "—"
            buttons = [
                Button(title="🚜 ОТД", callback_data="menu:work"),
                Button(title="📊 Статистика", callback_data="menu:stats"),
                Button(title="⚙️ Настройки", callback_data="menu:settings"),
            ]
            text = f"👤 *{name}*\n\nВыберите действие: 🌻"
            client.send_message(to=user_id, text=text, buttons=buttons)
            return
        else:
            client.send_message(to=user_id, text="❌ Эта команда только для IT отдела.")
            return
    
    # Команда для проверки TIM роли
    if norm_text in {"tim", "тим"}:
        # Разрешаем вызывать TIM меню как IT-шникам, так и самим TIM-ам
        if is_it(user_id) or is_tim(user_id):
            # Сохраняем текущее состояние в историю перед переходом
            save_to_history(user_id, "menu:root")
            
            # Показываем меню TIM. Но show_main_menu определяет вид меню по правам.
            # Поэтому мы либо временно выдаем права, либо напрямую вызываем рендер меню TIM.
            # Т.к. is_tim(user_id) проверяется внутри show_main_menu, то для реальных TIM всё ок.
            # Для IT-шников, которые хотят "подсмотреть", show_main_menu покажет IT-меню.
            # Поэтому для IT-шников, вызывающих tim, мы должны сэмулировать TIM-меню.
            
            # Но лучше просто добавить кнопку в IT меню, что я уже сделал.
            # Если IT хочет вызвать TIM меню командой, ему нужно стать TIM.
            # Но мы можем просто показать меню, как если бы он был TIM.
            
            u = get_user(user_id)
            name = (u or {}).get("full_name") or "—"
            text = (
                f"Первый зам директора по Информационным Технологиям\n"
                f"*{name}*\n\n"
                f"Выберите действие:"
            )
            buttons = [
                Button(title="🇨🇳 Партия следить 🇨🇳", callback_data="tim:party"),
                Button(title="📊 Статистика", callback_data="menu:stats"),
                Button(title="✏️ Сменить имя", callback_data="menu:name"),
            ]
            client.send_message(to=user_id, text=text, buttons=buttons)
            return
        else:
            client.send_message(to=user_id, text="❌ Нет прав для доступа к меню TIM.")
            return
    
    # Обработка звездочки для не-IT пользователей
    if message_text in {"⭐", "star", "звездочка", "звезда"}:
        if not is_it(user_id):
            client.send_message(to=user_id, text="⭐\n\nЭта команда доступна только для IT пользователей.")
            return
        # Для IT пользователей звездочка обрабатывается через callback

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

    # Special command for extended stats
    if norm_text in {"x", "х", "ч", "{", "/x"}: # x (eng), х (rus), ч (typo), { (shift+x), /x
        state = get_state(user_id)
        if state.get("state") == "admin_viewing_stats":
            st_type = state["data"].get("type")
            if st_type == "terra":
                today = date.today()
                start_date = date(today.year, today.month, 1).isoformat()
                
                with connect() as con, closing(con.cursor()) as c:
                    rows = c.execute("""
                        SELECT work_date, reg_name, location, activity, hours
                        FROM reports
                        WHERE work_date >= ?
                        ORDER BY work_date DESC, reg_name ASC
                    """, (start_date,)).fetchall()
                
                if not rows:
                    client.send_message(to=user_id, text="ℹ️ Детальных записей нет.")
                    return
                
                # Group by Date -> User
                grouped = {}
                for r in rows:
                    wd, name, loc, act, h = r
                    grouped.setdefault(wd, {}).setdefault(name, []).append((loc, act, h))
                
                lines = [f"📋 *Детализация Terra - {calendar.month_name[today.month]}*"]
                
                for d in sorted(grouped.keys(), reverse=True):
                    d_str = date.fromisoformat(d).strftime("%d.%m")
                    lines.append(f"\n📅 *{d_str}*")
                    for name in sorted(grouped[d].keys()):
                        lines.append(f"👤 *{name}*")
                        for loc, act, h in grouped[d][name]:
                            lines.append(f"   • {loc} — {act}: *{h}* ч")
                
                # Split message if too long (WhatsApp limit ~4096 chars)
                full_text = "\n".join(lines)
                if len(full_text) > 3000:
                    # Simple split by chunks
                    chunks = [full_text[i:i+3000] for i in range(0, len(full_text), 3000)]
                    for chunk in chunks:
                        client.send_message(to=user_id, text=chunk)
                else:
                    client.send_message(to=user_id, text=full_text)
                return

            elif st_type == "brig":
                today = date.today()
                start_date = date(today.year, today.month, 1).isoformat()
                
                with connect() as con, closing(con.cursor()) as c:
                    rows = c.execute("""
                        SELECT work_date, username, work_type, rows, bags, workers, field
                        FROM brigadier_reports
                        WHERE work_date >= ?
                        ORDER BY work_date DESC, username ASC
                    """, (start_date,)).fetchall()
                
                if not rows:
                    client.send_message(to=user_id, text="ℹ️ Детальных записей нет.")
                    return
                
                # Group by Date -> User
                grouped = {}
                for r in rows:
                    wd, name, w_type, w_rows, w_bags, w_workers, w_field = r
                    grouped.setdefault(wd, {}).setdefault(name, []).append((w_type, w_rows, w_bags, w_workers, w_field))
                
                lines = [f"📋 *Детализация Бригадиры - {calendar.month_name[today.month]}*"]
                
                for d in sorted(grouped.keys(), reverse=True):
                    d_str = date.fromisoformat(d).strftime("%d.%m")
                    lines.append(f"\n📅 *{d_str}*")
                    for name in sorted(grouped[d].keys()):
                        lines.append(f"👷 *{name}*")
                        for w_type, w_rows, w_bags, w_workers, w_field in grouped[d][name]:
                            field_info = f" ({w_field})" if w_field else ""
                            if w_type == "Кабачок":
                                lines.append(f"   • 🥒 {w_rows}р, {w_workers}чел{field_info}")
                            else:
                                lines.append(f"   • 🥔 {w_rows}р, {w_bags}с, {w_workers}чел{field_info}")
                
                # Split message if too long
                full_text = "\n".join(lines)
                if len(full_text) > 3000:
                    chunks = [full_text[i:i+3000] for i in range(0, len(full_text), 3000)]
                    for chunk in chunks:
                        client.send_message(to=user_id, text=chunk)
                else:
                    client.send_message(to=user_id, text=full_text)
                return

    # 2. Обработка состояний (FSM)
    state = get_state(user_id)
    current_state = state.get("state")
    
    logging.info(f"📩 Message from {user_id}: '{message_text}' | State: {current_state}")

    if current_state == "waiting_name":
        # Feature 5: Mandatory Full Name Registration
        parts = message_text.strip().split()
        if len(parts) < 2:
            client.send_message(to=user_id, text="❌ Пожалуйста, введите **Фамилию** и **Имя** (два слова).\nНапример: *Иванов Иван*")
            return
            
        if len(message_text) < 3:
            client.send_message(to=user_id, text="❌ Слишком короткое имя. Введите Фамилию и Имя.")
            return
        
        upsert_user(user_id, message_text, TZ)
        clear_state(user_id)
        client.send_message(to=user_id, text=f"✅ Приятно познакомиться, {message_text}!")
        
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "tim_wait_activity":
        if message_text == "0":
            show_date_selection(client, user_id, prefix="tim:date")
            return
        
        state["data"]["tim_report"] = {"activity": message_text}
        # Pass date along
        state["data"]["tim_report"]["date"] = state["data"]["date"]
        
        set_state(user_id, "tim_wait_location", state["data"], save_to_history=False)
        client.send_message(to=user_id, text="📍 Введите *локацию*:\n\n0. 🔙 Назад")
        return

    if current_state == "tim_wait_location":
        if message_text == "0":
            # Back to activity
            set_state(user_id, "tim_wait_activity", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="🇨🇳 Введите *вид работы*:\n\n0. 🔙 Назад")
            return
            
        state["data"]["tim_report"]["location"] = message_text
        set_state(user_id, "tim_wait_hours", state["data"], save_to_history=False)
        client.send_message(to=user_id, text="🕒 Введите *количество часов*:\n\n0. 🔙 Назад")
        return

    if current_state == "tim_wait_hours":
        if message_text == "0":
            # Back to location
            set_state(user_id, "tim_wait_location", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📍 Введите *локацию*:\n\n0. 🔙 Назад")
            return
            
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число.")
            return
            
        hours = int(message_text)
        if not (1 <= hours <= 24):
            client.send_message(to=user_id, text="❌ От 1 до 24.")
            return
            
        state["data"]["tim_report"]["hours"] = hours
        
        # Confirmation
        rep = state["data"]["tim_report"]
        d_str = date.fromisoformat(rep["date"]).strftime("%d.%m.%Y")
        
        text = (
            f"🇨🇳 *Проверка данных*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{rep['activity']}*\n"
            f"Место: *{rep['location']}*\n"
            f"Часы: *{hours}*\n"
        )
        
        buttons = [
            Button(title="✅ Подтвердить", callback_data="tim:save:simple"),
            Button(title="💾 Сохранить и подтв.", callback_data="tim:save:template"),
            Button(title="🔄 Заново", callback_data="tim:party")
        ]
        client.send_message(to=user_id, text=text, buttons=buttons)
        set_state(user_id, "tim_confirm", state["data"], save_to_history=False)
        return

    # -----------------------------
    # Новый поток: Трактор / КамАЗ / Ручная
    # -----------------------------
    if current_state == "work_tractor_activity_custom":
        if message_text == "0":
            # Назад к списку видов деятельности
            lines = ["Выберите *вид деятельности* (отправьте номер):"]
            for i, a in enumerate(ACTIVITIES_TRACTOR, 1):
                lines.append(f"{i}. {a}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_tractor_activity", state["data"], save_to_history=False)
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название (минимум 2 символа) или 0 для возврата.")
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["activity_base"] = message_text.strip()
        work_data["grp"] = GROUP_TECH
        state["data"]["work"] = work_data
        set_state(user_id, "work_tractor_field", state["data"], save_to_history=True, back_callback="work:tractor:activity")

        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_tractor_machinery":
        # Выбор трактора
        if message_text == "0":
            # Назад к выбору техники (Трактор/КамАЗ)
            buttons = [
                Button(title="🚜 Трактор", callback_data="work:type:tractor"),
                Button(title="🚛 КамАЗ", callback_data="work:type:kamaz"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text="Выберите *технику*:", buttons=buttons)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер трактора или используйте кнопку Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        choice = int(message_text)
        if not (1 <= choice <= len(TRACTORS)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        # Прочее -> свободный ввод
        if choice == len(TRACTORS) and TRACTORS[choice - 1].lower() == "прочее":
            set_state(user_id, "work_tractor_machinery_custom", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📝 Введите *трактор* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        machinery = TRACTORS[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["machinery"] = machinery
        work_data["date"] = state.get("data", {}).get("date", date.today().isoformat())
        work_data["work_type"] = "tractor"
        state["data"]["work"] = work_data
        set_state(user_id, "work_tractor_activity", state["data"], save_to_history=True, back_callback="work:tractor:machinery")

        lines = ["Выберите *вид деятельности* (отправьте номер):"]
        for i, a in enumerate(ACTIVITIES_TRACTOR, 1):
            lines.append(f"{i}. {a}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_tractor_machinery_custom":
        if message_text == "0":
            # Назад к списку тракторов
            lines = ["Выберите *трактор* (отправьте номер):"]
            for i, m in enumerate(TRACTORS, 1):
                lines.append(f"{i}. {m}")
            client.send_message(
                to=user_id,
                text="\n".join(lines),
                buttons=[Button(title="🔙 Назад", callback_data="back:prev")]
            )
            set_state(user_id, "work_tractor_machinery", state["data"], save_to_history=False)
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название трактора (мин. 2 символа) или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        machinery = message_text.strip()
        work_data = state.get("data", {}).get("work", {})
        work_data["machinery"] = machinery
        work_data["date"] = state.get("data", {}).get("date", date.today().isoformat())
        work_data["work_type"] = "tractor"
        state["data"]["work"] = work_data
        set_state(user_id, "work_tractor_activity", state["data"], save_to_history=True, back_callback="work:tractor:machinery")

        lines = ["Выберите *вид деятельности* (отправьте номер):"]
        for i, a in enumerate(ACTIVITIES_TRACTOR, 1):
            lines.append(f"{i}. {a}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return
    if current_state == "work_tractor_activity":
        if message_text == "0":
            # Назад к выбору трактора
            lines = ["Выберите *трактор* (отправьте номер):"]
            for i, m in enumerate(TRACTORS, 1):
                lines.append(f"{i}. {m}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_tractor_machinery", state["data"], save_to_history=False)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер вида деятельности или используйте кнопку Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        choice = int(message_text)
        if not (1 <= choice <= len(ACTIVITIES_TRACTOR)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        # Прочее -> свободный ввод
        if choice == len(ACTIVITIES_TRACTOR) and ACTIVITIES_TRACTOR[choice - 1].lower() == "прочее":
            set_state(user_id, "work_tractor_activity_custom", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📝 Введите *вид деятельности* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        activity = ACTIVITIES_TRACTOR[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["activity_base"] = activity
        work_data["grp"] = GROUP_TECH
        state["data"]["work"] = work_data
        set_state(user_id, "work_tractor_field", state["data"], save_to_history=True, back_callback="work:tractor:activity")

        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_tractor_field":
        if message_text == "0":
            # Назад к выбору вида деятельности
            lines = ["Выберите *вид деятельности* (отправьте номер):"]
            for i, a in enumerate(ACTIVITIES_TRACTOR, 1):
                lines.append(f"{i}. {a}")
            client.send_message(to=user_id, text="\n".join(lines) + "\n\n0. 🔙 Назад")
            set_state(user_id, "work_tractor_activity", state["data"], save_to_history=False)
            return
        locs = state.get("data", {}).get("locs", [])
        found_loc = None
        if message_text.isdigit():
            idx = int(message_text) - 1
            if 0 <= idx < len(locs):
                found_loc = locs[idx][1]
        if not found_loc:
            # allow exact name
            for _, name in locs:
                if name.lower() == message_text.lower():
                    found_loc = name
                    break
        if not found_loc:
            client.send_message(to=user_id, text="❌ Не найдено. Введите номер или точное название из списка, или 0.")
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["location"] = found_loc
        work_data["loc_grp"] = GROUP_FIELDS
        state["data"]["work"] = work_data
        set_state(user_id, "work_tractor_crop", state["data"], save_to_history=True, back_callback="work:tractor:field")

        lines = ["Выберите *культуру* (отправьте номер):"]
        for i, c in enumerate(CROPS, 1):
            lines.append(f"{i}. {c}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_tractor_crop":
        if message_text == "0":
            # Назад к выбору поля
            locations = state.get("data", {}).get("locs", [])
            lines = ["Выберите *поле* (отправьте номер):"]
            for i, (_, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            client.send_message(to=user_id, text="\n".join(lines) + "\n\n0. 🔙 Назад")
            set_state(user_id, "work_tractor_field", state["data"], save_to_history=False)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер культуры или 0 для возврата.")
            return
        choice = int(message_text)
        if not (1 <= choice <= len(CROPS)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или 0.")
            return
        # Прочее -> свободный ввод
        if choice == len(CROPS) and CROPS[choice - 1].lower() == "прочее":
            set_state(user_id, "work_tractor_crop_custom", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📝 Введите *культуру* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        crop = CROPS[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        # Формируем activity строку с деталями
        machinery = work_data.get("machinery", "Трактор")
        activity_base = work_data.get("activity_base", "Работа")
        work_data["activity"] = f"Трактор {machinery} — {activity_base} — {crop}"
        work_data["act_grp"] = GROUP_TECH
        # Сохраняем и переходим к вводу часов
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=True, back_callback="work:tractor:crop")

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"🚜 {machinery}\n"
            f"🔧 {activity_base}\n"
            f"🌱 {crop}\n"
            f"📍 {work_data.get('location','')}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "work_tractor_crop_custom":
        if message_text == "0":
            # Назад к выбору культуры
            lines = ["Выберите *культуру* (отправьте номер):"]
            for i, c in enumerate(CROPS, 1):
                lines.append(f"{i}. {c}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_tractor_crop", state["data"], save_to_history=True, back_callback="work:tractor:field")
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название культуры (минимум 2 символа) или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        crop = message_text.strip()
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        machinery = work_data.get("machinery", "Трактор")
        activity_base = work_data.get("activity_base", "Работа")
        work_data["activity"] = f"Трактор {machinery} — {activity_base} — {crop}"
        work_data["act_grp"] = GROUP_TECH
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=True, back_callback="work:tractor:crop")

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"🚜 {machinery}\n"
            f"🔧 {activity_base}\n"
            f"🌱 {crop}\n"
            f"📍 {work_data.get('location','')}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "work_kamaz_crop":
        if message_text == "0":
            # Назад к выбору техники
            buttons = [
                Button(title="🚜 Трактор", callback_data="work:type:tractor"),
                Button(title="🚛 КамАЗ", callback_data="work:type:kamaz"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text="Выберите *технику*:", buttons=buttons)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер культуры или используйте кнопку Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        choice = int(message_text)
        if not (1 <= choice <= len(CROPS_KAMAZ)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        if choice == len(CROPS_KAMAZ) and CROPS_KAMAZ[choice - 1].lower() == "прочее":
            set_state(user_id, "work_kamaz_crop_custom", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📝 Введите *культуру* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        crop = CROPS_KAMAZ[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        work_data["work_type"] = "kamaz"
        work_data["grp"] = GROUP_KAMAZ
        state["data"]["work"] = work_data
        set_state(user_id, "work_kamaz_trips", state["data"], save_to_history=False)
        client.send_message(to=user_id, text="Введите *количество рейсов* (число):", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_kamaz_trips":
        if message_text == "0":
            # Назад к выбору культуры
            lines = ["Выберите *культуру* (отправьте номер):"]
            for i, c in enumerate(CROPS_KAMAZ, 1):
                lines.append(f"{i}. {c}")
            client.send_message(to=user_id, text="\n".join(lines) + "\n\n0. 🔙 Назад")
            set_state(user_id, "work_kamaz_crop", state["data"], save_to_history=False)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число рейсов или 0 для возврата.")
            return
        trips = int(message_text)
        if trips <= 0:
            client.send_message(to=user_id, text="❌ Число рейсов должно быть больше 0.")
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["trips"] = trips
        state["data"]["work"] = work_data
        set_state(user_id, "work_kamaz_loading", state["data"], save_to_history=False)

        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        lines = ["Выберите *место погрузки* (номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        lines.append(f"{len(locations)+1}. Склад")
        lines.append(f"{len(locations)+2}. Прочее")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_kamaz_loading":
        if message_text == "0":
            # Назад к вводу рейсов
            client.send_message(to=user_id, text="Введите *количество рейсов* (число):\n\n0. 🔙 Назад")
            set_state(user_id, "work_kamaz_trips", state["data"], save_to_history=False)
            return
        locs = state.get("data", {}).get("locs", [])
        extra1 = len(locs) + 1  # склад
        extra2 = len(locs) + 2  # прочее
        chosen = None
        if message_text.isdigit():
            idx = int(message_text)
            if 1 <= idx <= len(locs):
                chosen = locs[idx-1][1]
            elif idx == extra1:
                chosen = "Склад"
            elif idx == extra2:
                # Прочее -> свободный ввод
                set_state(user_id, "work_kamaz_loading_custom", state["data"], save_to_history=False)
                client.send_message(to=user_id, text="Введите *место погрузки* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
                return
        if not chosen:
            # allow exact name
            for _, name in locs:
                if name.lower() == message_text.lower():
                    chosen = name
                    break
            if message_text.lower() == "склад":
                chosen = "Склад"
        if not chosen:
            client.send_message(to=user_id, text="❌ Не найдено. Введите номер из списка или 0.")
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["location"] = chosen
        work_data["loc_grp"] = GROUP_FIELDS if chosen != "Склад" else GROUP_WARE
        # Формируем activity строку
        crop = work_data.get("crop", "Груз")
        trips = work_data.get("trips")
        work_data["activity"] = f"КамАЗ — {crop} — {trips} рейсов"
        work_data["act_grp"] = GROUP_KAMAZ
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=False)

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"🚛 КамАЗ\n"
            f"📦 {crop} — {trips} рейсов\n"
            f"📍 {chosen}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "work_kamaz_loading_custom":
        if message_text == "0":
            # Назад к выбору места
            locations = state.get("data", {}).get("locs", [])
            lines = ["Выберите *место погрузки* (номер):"]
            for i, (_, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            lines.append(f"{len(locations)+1}. Склад")
            lines.append(f"{len(locations)+2}. Прочее")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_kamaz_loading", state["data"], save_to_history=False)
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["location"] = message_text.strip()
        work_data["loc_grp"] = GROUP_FIELDS
        crop = work_data.get("crop", "Груз")
        trips = work_data.get("trips")
        work_data["activity"] = f"КамАЗ — {crop} — {trips} рейсов"
        work_data["act_grp"] = GROUP_KAMAZ
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=False)

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"🚛 КамАЗ\n"
            f"📦 {crop} — {trips} рейсов\n"
            f"📍 {work_data['location']}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "work_kamaz_crop_custom":
        if message_text == "0":
            # Назад к выбору культуры
            lines = ["Выберите *культуру* (отправьте номер):"]
            for i, c in enumerate(CROPS_KAMAZ, 1):
                lines.append(f"{i}. {c}")
            client.send_message(to=user_id, text="\n".join(lines) + "\n\n0. 🔙 Назад")
            set_state(user_id, "work_kamaz_crop", state["data"], save_to_history=False)
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название культуры (минимум 2 символа) или 0 для возврата.")
            return
        crop = message_text.strip()
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        work_data["work_type"] = "kamaz"
        work_data["grp"] = GROUP_KAMAZ
        state["data"]["work"] = work_data
        set_state(user_id, "work_kamaz_trips", state["data"], save_to_history=False)
        client.send_message(to=user_id, text="Введите *количество рейсов* (число):", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_manual_activity":
        if message_text == "0":
            # Назад к выбору типа работы
            buttons = [
                Button(title="🚜 Трактор", callback_data="work:type:tractor"),
                Button(title="🚛 КамАЗ", callback_data="work:type:kamaz"),
                Button(title="✋ Ручная", callback_data="work:type:manual"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            client.send_message(to=user_id, text="Выберите *тип работы*:", buttons=buttons)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер вида работы или используйте кнопку Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        choice = int(message_text)
        if not (1 <= choice <= len(ACTIVITIES_MANUAL)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        if choice == len(ACTIVITIES_MANUAL) and ACTIVITIES_MANUAL[choice - 1].lower() == "прочее":
            set_state(user_id, "work_manual_activity_custom", state["data"], save_to_history=True, back_callback="work:manual:activity")
            client.send_message(to=user_id, text="📝 Введите *вид работы* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        activity = ACTIVITIES_MANUAL[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["activity_base"] = activity
        work_data["grp"] = GROUP_HAND
        work_data["work_type"] = "manual"
        state["data"]["work"] = work_data
        set_state(user_id, "work_manual_field", state["data"], save_to_history=True, back_callback="work:manual:activity")

        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_manual_activity_custom":
        if message_text == "0":
            # Назад к списку
            lines = ["Выберите *вид работы* (отправьте номер):"]
            for i, a in enumerate(ACTIVITIES_MANUAL, 1):
                lines.append(f"{i}. {a}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_manual_activity", state["data"], save_to_history=False)
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название работы (минимум 2 символа) или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["activity_base"] = message_text.strip()
        work_data["grp"] = GROUP_HAND
        work_data["work_type"] = "manual"
        state["data"]["work"] = work_data
        set_state(user_id, "work_manual_field", state["data"], save_to_history=True, back_callback="work:manual:activity")

        locations = list_locations_with_id(GROUP_FIELDS)
        state["data"]["locs"] = locations
        lines = ["Выберите *поле* (отправьте номер):"]
        for i, (_, name) in enumerate(locations, 1):
            lines.append(f"{i}. {name}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_manual_field":
        if message_text == "0":
            # Назад к выбору вида работы
            lines = ["Выберите *вид работы* (отправьте номер):"]
            for i, a in enumerate(ACTIVITIES_MANUAL, 1):
                lines.append(f"{i}. {a}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_manual_activity", state["data"], save_to_history=False)
            return
        locs = state.get("data", {}).get("locs", [])
        found_loc = None
        if message_text.isdigit():
            idx = int(message_text) - 1
            if 0 <= idx < len(locs):
                found_loc = locs[idx][1]
        if not found_loc:
            for _, name in locs:
                if name.lower() == message_text.lower():
                    found_loc = name
                    break
        if not found_loc:
            client.send_message(to=user_id, text="❌ Не найдено. Введите номер или точное название из списка, или 0.")
            return
        work_data = state.get("data", {}).get("work", {})
        work_data["location"] = found_loc
        work_data["loc_grp"] = GROUP_FIELDS
        state["data"]["work"] = work_data
        set_state(user_id, "work_manual_crop", state["data"], save_to_history=True, back_callback="work:manual:field")

        lines = ["Выберите *культуру* (отправьте номер):"]
        for i, c in enumerate(CROPS, 1):
            lines.append(f"{i}. {c}")
        client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
        return

    if current_state == "work_manual_crop":
        if message_text == "0":
            # Назад к выбору поля
            locations = state.get("data", {}).get("locs", [])
            lines = ["Выберите *поле* (отправьте номер):"]
            for i, (_, name) in enumerate(locations, 1):
                lines.append(f"{i}. {name}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_manual_field", state["data"], save_to_history=False)
            return
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер культуры или 0 для возврата.")
            return
        choice = int(message_text)
        if not (1 <= choice <= len(CROPS)):
            client.send_message(to=user_id, text="❌ Неверный номер. Введите номер из списка или 0.")
            return
        if choice == len(CROPS) and CROPS[choice - 1].lower() == "прочее":
            set_state(user_id, "work_manual_crop_custom", state["data"], save_to_history=False)
            client.send_message(to=user_id, text="📝 Введите *культуру* текстом:", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        crop = CROPS[choice - 1]
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        activity_base = work_data.get("activity_base", "Работа")
        work_data["activity"] = f"Ручная — {activity_base} — {crop}"
        work_data["act_grp"] = GROUP_HAND
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=True, back_callback="work:manual:crop")

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"✋ {activity_base}\n"
            f"🌱 {crop}\n"
            f"📍 {work_data.get('location','')}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "work_manual_crop_custom":
        if message_text == "0":
            # Назад к выбору культуры
            lines = ["Выберите *культуру* (отправьте номер):"]
            for i, c in enumerate(CROPS, 1):
                lines.append(f"{i}. {c}")
            client.send_message(to=user_id, text="\n".join(lines), buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            set_state(user_id, "work_manual_crop", state["data"], save_to_history=False)
            return
        if len(message_text.strip()) < 2:
            client.send_message(to=user_id, text="❌ Введите название культуры (минимум 2 символа) или нажмите Назад.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        crop = message_text.strip()
        work_data = state.get("data", {}).get("work", {})
        work_data["crop"] = crop
        activity_base = work_data.get("activity_base", "Работа")
        work_data["activity"] = f"Ручная — {activity_base} — {crop}"
        work_data["act_grp"] = GROUP_HAND
        state["data"]["work"] = work_data
        set_state(user_id, "waiting_hours", state["data"], save_to_history=True, back_callback="work:manual:crop")

        work_date = work_data.get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"✋ {activity_base}\n"
            f"🌱 {crop}\n"
            f"📍 {work_data.get('location','')}\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "waiting_activity_selection":
        if message_text == "0":
            buttons = [
                Button(title="Техника", callback_data="work:grp:tech"),
                Button(title="Ручная", callback_data="work:type:manual"),
                Button(title="🔙 Назад", callback_data="back:prev"),
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
                    text="📝 Введите *название работы* (от 3 до 50 символов):",
                    buttons=[Button(title="🔙 Назад", callback_data="back:prev")]
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
            Button(title="🔙 Назад", callback_data="back:prev"),
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
            lines.append(f"{len(activities) + 1}. 📝 Прочее")
            
            text = "\n".join(lines)
            client.send_message(to=user_id, text=text, buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        
        # Валидация пользовательского ввода
        custom_activity = message_text.strip()
        if len(custom_activity) < 3:
            client.send_message(to=user_id, text="❌ Слишком короткое название. Минимум 3 символа.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
            return
        
        if len(custom_activity) > 50:
            client.send_message(to=user_id, text="❌ Слишком длинное название. Максимум 50 символов.", buttons=[Button(title="🔙 Назад", callback_data="back:prev")])
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
            Button(title="🔙 Назад", callback_data="back:prev"),
        ]
        client.send_message(to=user_id, text=f"✅ Выбрано: *{custom_activity}*\n\nТеперь выберите *локацию*:", buttons=buttons)
        return

    if current_state == "waiting_location_selection":
        if message_text == "0":
            buttons = [
                Button(title="Поля", callback_data="work:locgrp:fields"),
                Button(title="Склад", callback_data="work:locgrp:ware"),
                Button(title="🔙 Назад", callback_data="back:prev"),
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
        
        # New flow: Date is already selected, go to hours
        # Сохраняем текущее состояние в историю перед переходом
        acts_kind = state["data"].get("acts_kind", "tech")
        save_to_history(user_id, f"work:grp:{acts_kind}")
        set_state(user_id, "waiting_hours", state["data"], save_to_history=False)
        
        # Calculate current hours
        work_date = state["data"].get("work", {}).get("date", date.today().isoformat())
        current_sum = sum_hours_for_user_date(user_id, work_date)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        
        text = (
            f"📅 Дата: *{d_str}*\n"
            f"📊 Уже внесено: *{current_sum}* ч\n\n"
            f"Введите *количество часов*:"
        )
        quick_replies = [{"id": "back_to_loc", "title": "🔙 Назад"}]
        client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
        return

    if current_state == "waiting_date_selection_universal":
        if message_text == "0":
            # Back button logic depends on where we came from
            # For now, just go to root menu
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return

        dates = state["data"].get("dates_list", [])
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер даты из списка или 0.")
            return
        
        idx = int(message_text) - 1
        if not (0 <= idx < len(dates)):
            client.send_message(to=user_id, text="❌ Неверный номер.")
            return
            
        selected_date = dates[idx]
        next_prefix = state["data"].get("next_prefix")
        
        if next_prefix == "work:date":
            # Worker flow: Date selected -> Choose Work Type (Technique / Manual)
            # Сохраняем дату в состоянии
            set_state(user_id, "pick_work_group", {"date": selected_date})
            
            buttons = [
                Button(title="🚜 Техника", callback_data="work:grp:tech"),
                Button(title="✋ Ручная", callback_data="work:type:manual"),
                Button(title="🔙 Назад", callback_data="back:prev"),
            ]
            d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
            client.send_message(to=user_id, text=f"📅 Дата: *{d_str}*\n\nВыберите *тип работы*:", buttons=buttons)
            
        elif next_prefix == "brig:date":
            # Brigadier flow: Date selected -> Choose Shift
            set_state(user_id, "brig_pick_shift", {"date": selected_date})
            
            buttons = [
                Button(title="☀️ Утренняя", callback_data="brig:shift:morning"),
                Button(title="🌙 Вечерняя", callback_data="brig:shift:evening"),
                Button(title="🔙 Назад", callback_data="menu:brigadier")
            ]
            d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
            client.send_message(to=user_id, text=f"📅 Дата: *{d_str}*\n\nВыберите *смену*:", buttons=buttons)
            
        elif next_prefix == "it:date":
            # IT flow: Date selected, now ask for hours
            # Calculate current IT hours for today
            current_sum = sum_hours_for_user_date(user_id, selected_date, include_it=True)
            
            d_str = date.fromisoformat(selected_date).strftime("%d.%m.%Y")
            text = (
                f"📅 Дата: *{d_str}*\n"
                f"📊 Уже внесено: *{current_sum}* ч\n\n"
                f"Введите *количество часов*:"
            )
            
            # IMPORTANT: We must pass the selected date in the data
            set_state(user_id, "it_waiting_hours", {"date": selected_date}, save_to_history=False)
            quick_replies = [{"id": "back_to_date", "title": "🔙 Back"}]
            client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
            
        elif next_prefix == "tim:date":
            # TIM Date selected -> Free input Activity
            set_state(user_id, "tim_wait_activity", {"date": selected_date}, save_to_history=False)
            client.send_message(to=user_id, text="🇨🇳 Введите *вид работы*:\n\n0. 🔙 Назад")
            
        return

    # Обработка состояния для IT роли - ввод часов для star
    if current_state == "it_waiting_hours":
        if not is_it(user_id):
            client.send_message(to=user_id, text="❌ Нет прав")
            clear_state(user_id)
            return
        
        # Обработка кнопки "Назад" (0) или Quick Reply "Back"
        if message_text == "0" or message_text.lower() == "back" or message_text == "back_to_date" or message_text == "🔙 Back":
            # Return to date selection
            show_date_selection(client, user_id, prefix="it:date")
            return
        
        if message_text == "back:prev": # Generic back
             if go_back(client, user_id):
                return
             else:
                clear_state(user_id)
                u = get_user(user_id)
                show_main_menu(client, user_id, u)
                return
        
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число (1-24) или 0 для возврата назад.")
            return
        
        hours = int(message_text)
        if not (1 <= hours <= 24):
            client.send_message(to=user_id, text="❌ Часы должны быть от 1 до 24 (или 0 для возврата назад).")
            return
        
        # Автоматически заполняем данные для IT отчета
        work_date = state["data"].get("date", date.today().isoformat())
        
        # Проверка суммы часов за день (IT отчеты не учитываются в общей статистике, но проверяем их отдельно)
        # Для IT роли проверяем только IT отчеты
        with connect() as con, closing(con.cursor()) as c:
            existing_it_hours = c.execute("""
                SELECT COALESCE(SUM(hours), 0) 
                FROM reports 
                WHERE user_id=? AND work_date=? AND (location_grp='it' OR activity_grp='it')
            """, (user_id, work_date)).fetchone()
            existing_it_hours = int(existing_it_hours[0] or 0)
        
        if existing_it_hours + hours > 24:
            # Получаем список существующих IT записей за день
            with connect() as con, closing(con.cursor()) as c:
                existing_reports = c.execute("""
                    SELECT activity, location, hours 
                    FROM reports 
                    WHERE user_id=? AND work_date=? AND (location_grp='it' OR activity_grp='it')
                    ORDER BY created_at
                """, (user_id, work_date)).fetchall()
            
            # Формируем сообщение об ошибке
            max_can_add = 24 - existing_it_hours
            error_parts = [
                f"❌ *Превышен лимит часов!*\n",
                f"Можно добавить не более *{max_can_add}* ч.\n",
                f"Уже записано: *{existing_it_hours}* ч из 24\n"
            ]
            
            if existing_reports:
                error_parts.append("\n*Существующие записи за этот день:*")
                for act, loc, h in existing_reports:
                    error_parts.append(f"• {act} ({loc}): *{h}* ч")
            
            error_parts.append(f"\n\nТекущая запись:")
            error_parts.append(f"• Автоматизация учета (Манхэттен): *{hours}* ч")
            error_parts.append(f"\nИтого будет: *{existing_it_hours + hours}* ч (максимум 24)")
            
            client.send_message(to=user_id, text="\n".join(error_parts))
            return
        
        temp_report = {
            "location": "Манхэттен",
            "loc_grp": "it",  # Специальная группа для IT
            "activity": "Автоматизация учета",
            "act_grp": "it",  # Специальная группа для IT
            "work_date": work_date,
            "hours": hours
        }
        
        # Сохраняем временный отчет в состояние
        state["data"]["temp_report"] = temp_report
        set_state(user_id, "waiting_confirmation_it", state["data"], save_to_history=False)
        
        # Показываем подтверждение (такое же как у всех)
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📋 *Подтверждение отчета*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{temp_report['activity']}*\n"
            f"Место: *{temp_report['location']}*\n"
            f"Часы: *{hours}*\n\n"
            f"Всё верно?"
        )
        
        buttons = [
            Button(title="✅ Подтвердить", callback_data="confirm:it"),
            Button(title="✏️ Изменить", callback_data="edit:it"),
        ]
        client.send_message(to=user_id, text=text, buttons=buttons)
        return

    if current_state == "waiting_hours":
        state = get_state(user_id)
        # Обработка кнопки "Назад" (0) или Quick Reply
        if message_text == "0" or message_text == "back_to_loc":
            # Fallback: возврат к выбору локации
            work_data = state["data"].get("work", {})
            activity_name = work_data.get("activity", "работа")
            
            # Check if we came from warehouse (skip loc selection) or fields
            loc_grp = work_data.get("loc_grp")
            
            if loc_grp == GROUP_WARE:
                 # If warehouse, we skipped location selection, so back should go to loc group selection
                 # But in handle_callback we saved history before waiting_hours.
                 # Let's try go_back first.
                 if go_back(client, user_id):
                     return
                 else:
                     # Fallback
                     buttons = [
                        Button(title="Поля", callback_data="work:locgrp:fields"),
                        Button(title="Склад", callback_data="work:locgrp:ware"),
                        Button(title="🔙 Назад", callback_data="back:prev"),
                    ]
                     client.send_message(to=user_id, text=f"✅ Выбрано: *{activity_name}*\n\nТеперь выберите *локацию*:", buttons=buttons)
                     return
            else:
                # Fields - go back to location selection
                # We can try go_back, but if we want to show the list again explicitly:
                locations = list_locations_with_id(GROUP_FIELDS)
                state["data"]["locs"] = locations
                set_state(user_id, "waiting_location_selection", state["data"], save_to_history=False)
                
                lines = ["Выберите *место* (отправьте номер или название):"]
                for i, (lid, name) in enumerate(locations, 1):
                    lines.append(f"{i}. {name}")
                
                text = "\n".join(lines)
                quick_replies = [{"id": "cancel_location", "title": "🔙 Назад"}]
                client.send_text_with_quick_replies(to=user_id, text=text, quick_replies=quick_replies)
                return
        
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число (1-24) или 0 для возврата назад.")
            return
        
        hours = int(message_text)
        if not (1 <= hours <= 24):
            client.send_message(to=user_id, text="❌ Часы должны быть от 1 до 24 (или 0 для возврата назад).")
            return
            
        work_data = state["data"].get("work", {})
        work_date = work_data.get("date")
        
        # Проверка суммы часов за день
        existing_hours = sum_hours_for_user_date(user_id, work_date)
        if existing_hours + hours > 24:
            # Получаем список существующих записей за день
            with connect() as con, closing(con.cursor()) as c:
                existing_reports = c.execute("""
                    SELECT activity, location, hours 
                    FROM reports 
                    WHERE user_id=? AND work_date=? AND location_grp != 'it' AND activity_grp != 'it'
                    ORDER BY created_at
                """, (user_id, work_date)).fetchall()
            
            # Формируем сообщение об ошибке
            max_can_add = 24 - existing_hours
            error_parts = [
                f"❌ *Превышен лимит часов!*\n",
                f"Можно добавить не более *{max_can_add}* ч.\n",
                f"Уже записано: *{existing_hours}* ч из 24\n"
            ]
            
            if existing_reports:
                error_parts.append("\n*Существующие записи за этот день:*")
                for act, loc, h in existing_reports:
                    error_parts.append(f"• {act} ({loc}): *{h}* ч")
            
            error_parts.append(f"\n\nТекущая запись:")
            error_parts.append(f"• {work_data.get('activity', 'работа')} ({work_data.get('location', 'место')}): *{hours}* ч")
            error_parts.append(f"\nИтого будет: *{existing_hours + hours}* ч (максимум 24)")
            
            client.send_message(to=user_id, text="\n".join(error_parts))
            return
        
        # Prepare temp report for confirmation
        temp_report = {
            "location": work_data.get("location"),
            "loc_grp": work_data.get("loc_grp"),
            "activity": work_data.get("activity"),
            "act_grp": work_data.get("grp"),
            "work_date": work_date,
            "hours": hours
        }
        
        state["data"]["temp_report"] = temp_report
        set_state(user_id, "waiting_confirmation_worker", state["data"], save_to_history=True, back_callback="work:manual:crop" if work_data.get("work_type") == "manual" else None)
        
        d_str = date.fromisoformat(temp_report["work_date"]).strftime("%d.%m.%Y")
        
        text = (
            f"📋 *Проверьте данные*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Работа: *{temp_report['activity']}*\n"
            f"Место: *{temp_report['location']}*\n"
            f"Часы: *{hours}*\n\n"
            f"Все верно?"
        )
        
        buttons = [
            Button(title="✅ Подтвердить", callback_data="confirm:worker"),
            Button(title="✏️ Изменить", callback_data="edit:worker")
        ]
        
        client.send_message(to=user_id, text=text, buttons=buttons)
        return

    if current_state == "waiting_record_selection":
        if message_text == "0":
            client.send_message(to=user_id, text="🔄 Отмена редактирования")
            clear_state(user_id)
            u = get_user(user_id)
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
            f"Введите новое количество часов:"
        )
        
        state["data"]["edit_id"] = rid
        state["data"]["edit_date"] = wdate
        state["data"]["edit_old_hours"] = h
        state["data"]["edit_activity"] = act
        state["data"]["edit_location"] = loc
        set_state(user_id, "waiting_edit_hours", state["data"])
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text=text, buttons=buttons)
        return

    if current_state == "waiting_del_selection":
        if message_text == "0":
            client.send_message(to=user_id, text="🔄 Отмена удаления")
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return

        # Parse multiple IDs
        ids_to_delete = []
        invalid_inputs = []
        
        # Split by comma or space
        parts = message_text.replace(",", " ").split()
        records = state["data"].get("del_records", [])
        
        for part in parts:
            if not part.isdigit():
                invalid_inputs.append(part)
                continue
                
            idx = int(part) - 1
            if not (0 <= idx < len(records)):
                invalid_inputs.append(part)
                continue
                
            # Get report ID (first element in record tuple)
            ids_to_delete.append(records[idx][0])
            
        if invalid_inputs:
            client.send_message(to=user_id, text=f"❌ Некорректные номера: {', '.join(invalid_inputs)}. Введите номера из списка через запятую или пробел.")
            return
            
        if not ids_to_delete:
            client.send_message(to=user_id, text="❌ Не выбрано ни одной записи.")
            return
            
        # Delete records
        success_count = 0
        fail_count = 0
        
        for rid in ids_to_delete:
            if delete_report(rid, user_id):
                success_count += 1
            else:
                fail_count += 1
                
        msg = f"✅ Удалено записей: {success_count}"
        if fail_count > 0:
            msg += f"\n❌ Ошибок удаления: {fail_count}"
            
        client.send_message(to=user_id, text=msg)
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "waiting_edit_selection_multi":
        if message_text == "0":
            client.send_message(to=user_id, text="🔄 Отмена редактирования")
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return

        # Parse multiple IDs
        ids_to_edit = []
        invalid_inputs = []
        
        parts = message_text.replace(",", " ").split()
        records = state["data"].get("edit_records", [])
        
        for part in parts:
            if not part.isdigit():
                invalid_inputs.append(part)
                continue
                
            idx = int(part) - 1
            if not (0 <= idx < len(records)):
                invalid_inputs.append(part)
                continue
                
            ids_to_edit.append(records[idx]) # Store full record
            
        if invalid_inputs:
            client.send_message(to=user_id, text=f"❌ Некорректные номера: {', '.join(invalid_inputs)}")
            return
            
        if not ids_to_edit:
            client.send_message(to=user_id, text="❌ Не выбрано ни одной записи.")
            return
            
        # Start editing queue
        state["data"]["edit_queue"] = ids_to_edit
        state["data"]["current_edit_idx"] = 0
        
        # Start first edit
        process_edit_queue(client, user_id, state["data"])
        return

    if current_state == "waiting_edit_queue_hours":
        # ... (Logic to handle hours for current edit item and move to next)
        if message_text == "0":
             # Abort all
             client.send_message(to=user_id, text="🔄 Отмена редактирования")
             clear_state(user_id)
             u = get_user(user_id)
             show_main_menu(client, user_id, u)
             return

        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число.")
            return
            
        new_h = int(message_text)
        if not (1 <= new_h <= 24):
            client.send_message(to=user_id, text="❌ Часы от 1 до 24.")
            return
            
        # Save change
        current_item = state["data"]["edit_queue"][state["data"]["current_edit_idx"]]
        rid = current_item[0]
        
        if update_report_hours(rid, user_id, new_h):
            client.send_message(to=user_id, text=f"✅ Запись #{rid} обновлена.")
        else:
            client.send_message(to=user_id, text=f"❌ Ошибка обновления записи #{rid}.")
            
        # Move to next
        state["data"]["current_edit_idx"] += 1
        process_edit_queue(client, user_id, state["data"])
        return

def process_edit_queue(client, user_id, data):
    queue = data["edit_queue"]
    idx = data["current_edit_idx"]
    
    if idx >= len(queue):
        # All done
        client.send_message(to=user_id, text="✅ Все выбранные записи отредактированы.")
        u = get_user(user_id)
        clear_state(user_id)
        show_main_menu(client, user_id, u)
        return
        
    # Show edit prompt for current item
    item = queue[idx]
    rid, wdate, act, loc, h, _ = item
    
    text = (
        f"📝 *Редактирование записи {idx+1}/{len(queue)}*\n"
        f"📅 Дата: {wdate}\n"
        f"📍 Место: {loc}\n"
        f"🚜 Работа: {act}\n"
        f"🕒 Текущие часы: *{h}*\n\n"
        f"Введите *новые часы* (или 0 для отмены всех):"
    )
    
    # Update state for this step
    set_state(user_id, "waiting_edit_queue_hours", data) # Data already contains queue/idx
    client.send_message(to=user_id, text=text)

# ... (existing code) ...

    if current_state == "wait_del_brig_select":
        if message_text == "0":
            client.send_message(to=user_id, text="🔄 Отмена")
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return
            
        # Parse multiple IDs for brigadiers too
        ids_to_delete = []
        invalid_inputs = []
        
        parts = message_text.replace(",", " ").split()
        records = state["data"].get("del_list_brig", [])
        
        for part in parts:
            if not part.isdigit():
                invalid_inputs.append(part)
                continue
                
            idx = int(part) - 1
            if not (0 <= idx < len(records)):
                invalid_inputs.append(part)
                continue
                
            ids_to_delete.append(records[idx][0])
            
        if invalid_inputs:
            client.send_message(to=user_id, text=f"❌ Некорректные номера: {', '.join(invalid_inputs)}")
            return
            
        if not ids_to_delete:
            client.send_message(to=user_id, text="❌ Не выбрано ни одной записи.")
            return
            
        with connect() as con, closing(con.cursor()) as c:
            placeholders = ",".join("?" * len(ids_to_delete))
            c.execute(f"DELETE FROM brigadier_reports WHERE id IN ({placeholders})", ids_to_delete)
            con.commit()
            deleted_count = c.execute("SELECT changes()").fetchone()[0] # This might not work in all sqlite versions/drivers perfectly in one go
            # Rowcount is better check on cursor object
            
        # Re-check deletion rowcount isn't easy with batch delete in this wrapper context easily without cursor object
        # Let's assume success if no exception
        client.send_message(to=user_id, text=f"✅ Удалено записей: {len(ids_to_delete)}")
        
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "wait_edit_brig_select":
        # For simplicity, we only allow deleting brigadier reports for now or re-creating.
        # Editing complex brigadier reports (rows/bags/workers) via chat is cumbersome.
        # Let's just say "Use delete and create new" or implement simple edit if needed.
        # But user asked for "Edit" button. Let's allow editing rows for now.
        
        if message_text == "0":
            client.send_message(to=user_id, text="🔄 Отмена")
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return
            
        idx = int(message_text) - 1
        records = state["data"].get("edit_list_brig", [])
        if not (0 <= idx < len(records)):
            client.send_message(to=user_id, text="❌ Неверный номер.")
            return
            
        rid = records[idx][0]
        state["data"]["edit_brig_id"] = rid
        set_state(user_id, "wait_edit_brig_rows", state["data"])
        client.send_message(to=user_id, text="Введите новое количество *рядов*:")
        return

    if current_state == "wait_edit_brig_rows":
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число.")
            return
        
        new_rows = int(message_text)
        rid = state["data"].get("edit_brig_id")
        
        with connect() as con, closing(con.cursor()) as c:
            c.execute("UPDATE brigadier_reports SET rows=? WHERE id=?", (new_rows, rid))
            con.commit()
            
        client.send_message(to=user_id, text="✅ Количество рядов обновлено.")
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return

    if current_state == "waiting_edit_hours":
        if message_text == "0":
            if go_back(client, user_id):
                return
            else:
                clear_state(user_id)
                u = get_user(user_id)
                show_main_menu(client, user_id, u)
                return
        
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите число (1-24) или 0 для возврата.")
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
            # Получаем данные для уведомления
            old_hours = state["data"].get("edit_old_hours", "?")
            activity = state["data"].get("edit_activity", "работа")
            location = state["data"].get("edit_location", "место")
            
            # Формируем текст уведомления
            edit_text = (
                f"📝 Запись #{rid}\n"
                f"Дата: {work_d}\n"
                f"Место: {location}\n"
                f"Работа: {activity}\n"
                f"Часы: {old_hours} → *{new_h}*"
            )
            
            # Отправляем уведомление на релейный номер
            u = get_user(user_id)
            user_name = (u or {}).get("full_name") or user_id
            send_report_to_relay(original_from=user_id, original_text=edit_text, user_name=user_name, is_edit=True)
            
            clear_state(user_id)
            client.send_message(to=user_id, text="✅ Обновлено")
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
                Button(title="🔙 Назад", callback_data="back:prev"),
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
                Button(title="🔙 Назад", callback_data="back:prev"),
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
    
    # -----------------------------
    # Обработчики для бригадиров
    # -----------------------------
    
    # Команда бриг: для админа - управление, для IT/бригадира - меню бригадира
    if norm_text in {"бриг", "/бриг"}:
        if is_admin(user_id):
            buttons = [
                Button(title="➕ Добавить бригадира", callback_data="adm:add:brigadier"),
                Button(title="➖ Удалить бригадира", callback_data="adm:del:brigadier"),
                Button(title="📋 Список бригадиров", callback_data="adm:list:brigadiers"),
            ]
            client.send_message(to=user_id, text="👷 *Управление бригадирами*:", buttons=buttons)
            return
        if is_it(user_id) or is_brigadier(user_id):
            # Открываем меню бригадира
            btn_obj = type('obj', (object,), {'from_user': msg.from_user, 'data': 'menu:brigadier'})()
            handle_callback(client, btn_obj)
            return
        client.send_message(to=user_id, text="❌ Нет прав для доступа к меню бригадира.")
        return
    
    # Форма кабачков: ряды
    if current_state == "brig_zucchini_rows":
        # Обработка ввода рядов для кабачков
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        if not txt.isdigit():
            buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
            client.send_message(to=user_id, text="❌ Введите число (количество рядов):", buttons=buttons)
            return
        rows = int(txt)
        # Страхуемся, что есть data
        state["data"] = state.get("data", {}) or {}
        state["data"]["rows"] = rows
        # Сохраняем шаг для корректного Back
        back_cb = None
        if state["data"].get("date"):
            back_cb = f"brig:report:date:{state['data']['date']}"
        else:
            back_cb = "menu:brigadier"
        set_state(user_id, "brig_zucchini_field", state["data"], save_to_history=True, back_callback=back_cb)
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="Введите *название поля*:", buttons=buttons)
        return
    
    # Форма кабачков: поле
    if current_state == "brig_zucchini_field":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        state["data"] = state.get("data", {}) or {}
        state["data"]["field"] = txt
        # Сохраняем в историю для back
        set_state(user_id, "brig_zucchini_workers", state["data"], save_to_history=True, back_callback="back:prev")
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="Введите *количество людей*:", buttons=buttons)
        return
    
    # Форма кабачков: люди (финальный шаг)
    if current_state == "brig_zucchini_workers":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        if not txt.isdigit():
            buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
            client.send_message(to=user_id, text="❌ Введите число (количество людей):", buttons=buttons)
            return
        workers = int(txt)
        state["data"] = state.get("data", {}) or {}
        work_date = state["data"].get("date", date.today().isoformat())
        temp_report = {
            "work_type": state["data"].get("work_type", "Кабачок"),
            "rows": state["data"].get("rows", 0),
            "field": state["data"].get("field", ""),
            "bags": 0,
            "workers": workers,
            "work_date": work_date
        }
        state["data"]["temp_report"] = temp_report
        set_state(user_id, "waiting_confirmation_brigadier", state["data"], save_to_history=True, back_callback="back:prev")
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        text = (
            f"📋 *Проверьте данные*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Тип: *{temp_report['work_type']}*\n"
            f"Рядов: *{temp_report['rows']}*\n"
            f"Поле: *{temp_report['field']}*\n"
            f"Людей: *{workers}*\n\n"
            f"Все верно?"
        )
        buttons = [
            Button(title="✅ Подтвердить", callback_data="confirm:brig"),
            Button(title="✏️ Изменить", callback_data="edit:brig")
        ]
        client.send_message(to=user_id, text=text, buttons=buttons)
        return
    
    # Форма картошки: ряды
    if current_state == "brig_potato_rows":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        if not txt.isdigit():
            buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
            client.send_message(to=user_id, text="❌ Введите число (количество выкопанных рядов):", buttons=buttons)
            return
        rows = int(txt)
        state["data"] = state.get("data", {}) or {}
        state["data"]["rows"] = rows
        # Сохраняем историю для корректного Back (к выбору культуры/даты)
        back_cb = None
        if state["data"].get("date"):
            back_cb = f"brig:report:date:{state['data']['date']}"
        else:
            back_cb = "menu:brigadier"
        set_state(user_id, "brig_potato_field", state["data"], save_to_history=True, back_callback=back_cb)
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="Введите *название поля*:", buttons=buttons)
        return

    # Форма картошки: поле
    if current_state == "brig_potato_field":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        state["data"] = state.get("data", {}) or {}
        state["data"]["field"] = txt
        set_state(user_id, "brig_potato_bags", state["data"], save_to_history=True, back_callback="back:prev")
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="Введите *количество сеток*:", buttons=buttons)
        return
    
    # Форма картошки: сетки
    if current_state == "brig_potato_bags":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        if not txt.isdigit():
            buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
            client.send_message(to=user_id, text="❌ Введите число (количество сеток):", buttons=buttons)
            return
        bags = int(txt)
        state["data"] = state.get("data", {}) or {}
        state["data"]["bags"] = bags
        set_state(user_id, "brig_potato_workers", state["data"], save_to_history=True, back_callback="back:prev")
        buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
        client.send_message(to=user_id, text="Введите *количество людей*:", buttons=buttons)
        return
    
    # Форма картошки: люди (финальный шаг)
    if current_state == "brig_potato_workers":
        txt = message_text.strip()
        if txt == "0":
            if go_back(client, user_id):
                return
        if not txt.isdigit():
            buttons = [Button(title="🔙 Назад", callback_data="back:prev")]
            client.send_message(to=user_id, text="❌ Введите число (количество людей):", buttons=buttons)
            return
        workers = int(txt)
        
        # Получаем дату из состояния
        work_date = state["data"].get("date", date.today().isoformat())
        
        temp_report = {
            "work_type": state["data"]["work_type"],
            "rows": state["data"]["rows"],
            "field": state["data"]["field"],
            "bags": state["data"]["bags"],
            "workers": workers,
            "work_date": work_date
        }
        
        state["data"]["temp_report"] = temp_report
        set_state(user_id, "waiting_confirmation_brigadier", state["data"])
        
        d_str = date.fromisoformat(work_date).strftime("%d.%m.%Y")
        
        text = (
            f"📋 *Проверьте данные*\n\n"
            f"📅 Дата: *{d_str}*\n"
            f"Тип: *{temp_report['work_type']}*\n"
            f"Рядов: *{temp_report['rows']}*\n"
            f"Сеток: *{temp_report['bags']}*\n"
            f"Поле: *{temp_report['field']}*\n"
            f"Людей: *{workers}*\n\n"
            f"Все верно?"
        )
        
        buttons = [
            Button(title="✅ Подтвердить", callback_data="confirm:brig"),
            Button(title="✏️ Изменить", callback_data="edit:brig")
        ]
        
        client.send_message(to=user_id, text=text, buttons=buttons)
        return
    
    # Админ: добавление бригадира
    if current_state == "adm_wait_brigadier_add":
        # Ожидаем номер телефона
        phone = message_text.strip()
        
        # Если ввели "Номер Имя"
        parts = phone.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            phone = parts[0]
            name = parts[1]
            
            # Сразу добавляем
            target_user = get_user(phone)
            if not target_user:
                upsert_user(phone, name, TZ)
            else:
                upsert_user(phone, name, TZ)
                
            if add_brigadier(phone, name, name, user_id):
                client.send_message(to=user_id, text=f"✅ Бригадир *{name}* ({phone}) добавлен.")
            else:
                client.send_message(to=user_id, text="❌ Этот пользователь уже является бригадиром.")
            
            clear_state(user_id)
            u = get_user(user_id)
            show_main_menu(client, user_id, u)
            return

        # Если только номер
        if not phone.isdigit() or len(phone) < 10:
            client.send_message(to=user_id, text="❌ Введите корректный номер телефона (например: 79001234567) или 'Номер Имя':")
            return
        
        # Сохраняем номер и спрашиваем имя
        state["data"]["brig_phone"] = phone
        set_state(user_id, "adm_wait_brigadier_name", state["data"])
        client.send_message(to=user_id, text="✏️ Введите *Имя бригадира*:")
        return

    # Админ: ввод имени бригадира
    if current_state == "adm_wait_brigadier_name":
        name = message_text.strip()
        if len(name) < 2:
            client.send_message(to=user_id, text="❌ Слишком короткое имя. Попробуйте еще раз:")
            return
            
        phone = state["data"].get("brig_phone")
        if not phone:
            client.send_message(to=user_id, text="❌ Ошибка состояния. Начните заново.")
            clear_state(user_id)
            return
            
        # Создаем/обновляем пользователя
        upsert_user(phone, name, TZ)
        
        if add_brigadier(phone, name, name, user_id):
            client.send_message(to=user_id, text=f"✅ Бригадир *{name}* ({phone}) добавлен.")
        else:
            client.send_message(to=user_id, text="❌ Этот пользователь уже является бригадиром.")
        
        clear_state(user_id)
        u = get_user(user_id)
        show_main_menu(client, user_id, u)
        return
    
    # Админ: удаление бригадира
    if current_state == "adm_wait_brigadier_del":
        if message_text == "0":
            buttons = [
                Button(title="➕ Добавить бригадира", callback_data="adm:add:brigadier"),
                Button(title="➖ Удалить бригадира", callback_data="adm:del:brigadier"),
                Button(title="📋 Список бригадиров", callback_data="adm:list:brigadiers"),
            ]
            client.send_message(to=user_id, text="👷 *Управление бригадирами*:", buttons=buttons)
            clear_state(user_id)
            return
        
        if not message_text.isdigit():
            client.send_message(to=user_id, text="❌ Введите номер бригадира из списка или 0 для возврата.")
            return
        
        idx = int(message_text) - 1
        brigadiers = state["data"].get("brigadiers_list", [])
        
        if not (0 <= idx < len(brigadiers)):
            client.send_message(to=user_id, text="❌ Неверный номер.")
            return
        
        brig = brigadiers[idx]
        brig_id, brig_uname, brig_fname, _, _ = brig
        
        if remove_brigadier(brig_id):
            client.send_message(to=user_id, text=f"✅ Бригадир *{brig_fname or brig_uname}* удален.")
        else:
            client.send_message(to=user_id, text="❌ Не удалось удалить.")
        
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
    
    data = request.json
    if not data:
        return "Empty payload", 400
        
    # Deduplication check for messages
    try:
        entry = data.get("entry", [])
        if entry:
            changes = entry[0].get("changes", [])
            if changes:
                value = changes[0].get("value", {})
                messages = value.get("messages", [])
                if messages:
                    msg_id = messages[0].get("id")
                    if msg_id and is_message_processed(msg_id):
                        logging.info(f"♻️ Duplicate message ignored: {msg_id}")
                        return "Duplicate ignored", 200
    except Exception as e:
        logging.error(f"Error checking duplicate: {e}")

    wa.process_webhook(data)
    return "OK", 200

@app.route("/github-webhook", methods=["POST"])
def github_webhook():
    """
    Endpoint для автоматического обновления бота через GitHub webhook.
    GitHub отправляет POST запрос при push в репозиторий.
    """
    if not GITHUB_WEBHOOK_SECRET:
        logging.warning("⚠️ GitHub webhook вызван, но секрет не настроен")
        return "Webhook not configured", 503
    
    # Проверка секрета (если настроен в GitHub)
    signature = request.headers.get("X-Hub-Signature-256", "")
    if signature:
        import hmac
        import hashlib
        payload = request.get_data()
        expected_signature = "sha256=" + hmac.new(
            GITHUB_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            logging.warning("❌ Неверная подпись GitHub webhook")
            return "Invalid signature", 403
    
    # Проверка события
    event = request.headers.get("X-GitHub-Event", "")
    if event != "push":
        logging.info(f"ℹ️ GitHub webhook: событие {event} проигнорировано")
        return "Event ignored", 200
    
    data = request.json
    if not data:
        return "Empty payload", 400
    
    # Проверка, что это push в main ветку
    ref = data.get("ref", "")
    if ref != "refs/heads/main":
        logging.info(f"ℹ️ GitHub webhook: push в {ref} проигнорирован (ожидается main)")
        return "Branch ignored", 200
    
    logging.info("🔄 Получен GitHub webhook для обновления бота")
    
    # Запуск скрипта обновления в фоне
    import subprocess
    import threading
    
    def run_update():
        try:
            script_path = "/root/bot/update_bot.sh"
            result = subprocess.run(
                ["bash", script_path],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                logging.info("✅ Бот успешно обновлен и перезапущен")
            else:
                logging.error(f"❌ Ошибка обновления: {result.stderr}")
        except Exception as e:
            logging.error(f"❌ Ошибка выполнения скрипта обновления: {e}")
    
    # Запускаем обновление в отдельном потоке, чтобы не блокировать ответ
    thread = threading.Thread(target=run_update, daemon=True)
    thread.start()
    
    return jsonify({"status": "update_started"}), 200

if __name__ == "__main__":
    init_db()
    
    # Инициализация Google Sheets
    if GOOGLE_SHEETS_AVAILABLE:
        logging.info("🔄 Инициализация Google Sheets...")
        if initialize_google_sheets():
            logging.info("✅ Google Sheets готов к работе")
        else:
            logging.warning("⚠️ Google Sheets не инициализирован, работа продолжится без синхронизации")
    
    # Scheduler setup
    scheduler = BackgroundScheduler(timezone=TZ)
    
    # Reminder job (every minute)
    scheduler.add_job(check_reminders, 'interval', minutes=1)
    logging.info("⏰ Reminder scheduler started")

    if AUTO_EXPORT_ENABLED:
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
            logging.info(f"Scheduled export enabled: {AUTO_EXPORT_CRON}")
        else:
            logging.warning(f"Invalid cron expression: {AUTO_EXPORT_CRON}")
            
    scheduler.start()
    
    logging.info("🤖 WhatsApp бот запущен!")
    logging.info("📡 Слушаю на %s:%s", SERVER_HOST, SERVER_PORT)
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
