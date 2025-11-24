# bot_360_full.py - ПОЛНАЯ версия WhatsApp бота с 360dialog API
# Все функции из оригинального бота

import os
import sys
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, date
from typing import Dict, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass
import calendar

from dotenv import load_dotenv
from flask import Flask, request, jsonify

# 360dialog клиент
from whatsapp_360_client import WhatsApp360Client, Button

# Google Sheets
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Scheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Конфиг
load_dotenv()
logging.basicConfig(level=logging.INFO)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WA_BASE_URL = os.getenv("WA_BASE_URL", "https://waba-v2.360dialog.io")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
TZ = os.getenv("TZ", "Europe/Moscow").strip()

def _parse_admin_ids(s: str) -> List[str]:
    out = []
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        out.append(part.strip())
    return out

ADMIN_IDS = set(_parse_admin_ids(os.getenv("ADMIN_IDS", "")))
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
    logging.error("❌ WHATSAPP_TOKEN not found")
    sys.exit(1)

# Константы
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

# Состояния
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

# БД
def connect():
    return sqlite3.connect(DB_PATH)

def init_db():
    with connect() as con, closing(con.cursor()) as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          user_id TEXT PRIMARY KEY,
          full_name TEXT,
          tz TEXT,
          created_at TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS activities(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE,
          grp TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS locations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE,
          grp TEXT
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT,
          user_id TEXT,
          reg_name TEXT,
          location TEXT,
          location_grp TEXT,
          activity TEXT,
          activity_grp TEXT,
          work_date TEXT,
          hours INTEGER
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS google_exports(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id INTEGER UNIQUE,
          spreadsheet_id TEXT,
          sheet_name TEXT,
          row_number INTEGER,
          exported_at TEXT,
          last_updated TEXT,
          FOREIGN KEY (report_id) REFERENCES reports(id)
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS monthly_sheets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          year INTEGER,
          month INTEGER,
          spreadsheet_id TEXT,
          sheet_url TEXT,
          created_at TEXT,
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
        return c.lastrowid

def sum_hours_for_user_date(user_id:str, work_date:str, exclude_report_id: Optional[int] = None) -> int:
    with connect() as con, closing(con.cursor()) as c:
        if exclude_report_id:
            r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=? AND id<>?",
                          (user_id, work_date, exclude_report_id)).fetchone()
        else:
            r = c.execute("SELECT COALESCE(SUM(hours),0) FROM reports WHERE user_id=? AND work_date=?",
                          (user_id, work_date)).fetchone()
        return int(r[0] or 0)

def is_admin(user_id: str) -> bool:
    return user_id in ADMIN_IDS

# Flask
app = Flask(__name__)

# 360dialog клиент
wa = WhatsApp360Client(api_key=WHATSAPP_TOKEN, base_url=WA_BASE_URL)
logging.info("✅ 360dialog client initialized")

# Пагинация
@dataclass
class PaginationButton:
    title: str
    callback_data: str

def send_paginated_buttons(to: str, text: str, items: list, make_button, state_key: str, page: int = 0, back_cb: Optional[str] = None):
    if not items:
        wa.send_message(to=to, text=f"{text}\\n\\n_(Список пуст)_")
        return
    
    base_capacity = 2
    total_items = len(items)
    total_pages = (total_items + base_capacity - 1) // base_capacity
    page = max(0, min(page, total_pages - 1))
    
    start = page * base_capacity
    end = min(start + base_capacity, total_items)
    page_items = items[start:end]
    
    has_prev = page > 0
    has_next = page < total_pages - 1
    
    btns: list[Button] = []
    for it in page_items:
        b = make_button(it)
        if isinstance(b, Button):
            btns.append(b)
        else:
            btns.append(Button(title=b.title, callback_data=b.callback_data))
    
    if has_prev and len(btns) < 3:
        btns.append(Button(title="⬅️", callback_data=f"nav:{state_key}:{page-1}"))
    elif has_next and len(btns) < 3:
        btns.append(Button(title="➡️", callback_data=f"nav:{state_key}:{page+1}"))
    
    if back_cb and len(btns) < 3:
        btns.append(Button(title="🔙 Назад", callback_data=back_cb))
    
    page_info = f"\\n\\n_Страница {page+1} из {total_pages}_" if total_pages > 1 else ""
    wa.send_message(to=to, text=text + page_info, buttons=btns[:3])

# Меню
def show_main_menu(user_id: str, u: dict):
    name = (u or {}).get("full_name") or "—"
    text = f"👤 *{name}*\\n\\nВыберите действие:"
    buttons = [
        Button(title="🚜 Работа", callback_data="menu:work"),
        Button(title="📊 Статистика", callback_data="menu:stats"),
        Button(title="Ещё...", callback_data="menu:more"),
    ]
    wa.send_message(to=user_id, text=text, buttons=buttons)

# Обработчики
@wa.on_message
def handle_message(client, msg):
    user_id = msg.from_user.wa_id
    message_text = (msg.text or "").strip().lower()
    
    logging.info(f"📨 {user_id}: {message_text}")
    
    if message_text in {"menu", "меню", "start", "старт"}:
        upsert_user(user_id, msg.from_user.name, TZ)
        u = get_user(user_id)
        
        if not u or not (u.get("full_name") or "").strip():
            set_state(user_id, "waiting_name")
            wa.send_message(to=user_id, text="👋 Введите *Фамилию Имя*:")
            return
        
        show_main_menu(user_id, u)
        return
    
    state = get_state(user_id)
    current_state = state.get("state")
    
    if current_state == "waiting_name":
        full_name = msg.text.strip()
        if len(full_name) < 3:
            wa.send_message(to=user_id, text="❌ Имя слишком короткое.")
            return
        
        upsert_user(user_id, full_name, TZ)
        clear_state(user_id)
        u = get_user(user_id)
        wa.send_message(to=user_id, text=f"✅ Добро пожаловать, *{full_name}*!")
        show_main_menu(user_id, u)
        return
    
    elif current_state == "wait_hours":
        try:
            hours = int(msg.text.strip())
            if hours < 1 or hours > 24:
                raise ValueError()
        except:
            wa.send_message(to=user_id, text="❌ Введите число от 1 до 24.")
            return
        
        work_data = state["data"].get("work_data", {})
        already = sum_hours_for_user_date(user_id, work_data["work_date"])
        if already + hours > 24:
            max_can_add = 24 - already
            wa.send_message(to=user_id, text=f"❌ Превышен лимит! Можно добавить не более {max_can_add} ч.")
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
            f"✅ *Сохранено*\\n\\n"
            f"Дата: *{work_data['work_date']}*\\n"
            f"Место: *{work_data['location']}*\\n"
            f"Работа: *{work_data['activity']}*\\n"
            f"Часы: *{hours}*\\n"
            f"ID: `#{rid}`"
        )
        clear_state(user_id)
        wa.send_message(to=user_id, text=text)
        show_main_menu(user_id, u)
        return
    
    wa.send_message(to=user_id, text="🤖 Напишите *menu*.")

@wa.on_callback_button
def handle_callback(client, btn):
    user_id = btn.from_user.wa_id
    data = btn.data
    
    logging.info(f"🔘 {user_id}: {data}")
    
    if data == "menu:root":
        u = get_user(user_id)
        show_main_menu(user_id, u)
    
    elif data == "menu:work":
        buttons = [
            Button(title="🚜 Техника", callback_data="work:tech"),
            Button(title="✋ Ручная", callback_data="work:hand"),
            Button(title="🔙 Назад", callback_data="menu:root"),
        ]
        wa.send_message(to=user_id, text="Выберите *тип работы*:", buttons=buttons)
    
    elif data.startswith("work:"):
        kind = data.split(":")[1]
        grp = GROUP_TECH if kind == "tech" else GROUP_HAND
        
        acts = list_activities_with_id(grp)
        state = get_state(user_id)
        state["data"]["acts_kind"] = kind
        state["data"]["acts"] = acts
        set_state(user_id, "choosing_activity", state["data"])
        
        send_paginated_buttons(
            to=user_id,
            text="Выберите *вид работы*:",
            items=acts,
            make_button=lambda a: PaginationButton(title=a[1][:20], callback_data=f"act:{a[0]}"),
            state_key="acts",
            page=0,
            back_cb="menu:work"
        )
    
    elif data.startswith("act:"):
        act_id = int(data.split(":")[1])
        act_info = get_activity_name(act_id)
        if not act_info:
            wa.send_message(to=user_id, text="❌ Работа не найдена.")
            return
        
        activity, grp = act_info
        
        locs = list_locations_with_id(GROUP_FIELDS)
        state = get_state(user_id)
        state["data"]["activity"] = activity
        state["data"]["grp"] = grp
        state["data"]["locs"] = locs
        set_state(user_id, "choosing_location", state["data"])
        
        send_paginated_buttons(
            to=user_id,
            text=f"*{activity}*\\n\\nВыберите *место*:",
            items=locs,
            make_button=lambda l: PaginationButton(title=l[1][:20], callback_data=f"loc:{l[0]}"),
            state_key="locs",
            page=0,
            back_cb="menu:work"
        )
    
    elif data.startswith("loc:"):
        loc_id = int(data.split(":")[1])
        loc_info = get_location_name(loc_id)
        if not loc_info:
            wa.send_message(to=user_id, text="❌ Место не найдено.")
            return
        
        location, loc_grp = loc_info
        
        state = get_state(user_id)
        state["data"]["location"] = location
        state["data"]["loc_grp"] = loc_grp
        
        buttons = [
            Button(title="Сегодня", callback_data="date:today"),
            Button(title="Вчера", callback_data="date:yesterday"),
        ]
        wa.send_message(to=user_id, text=f"*{state['data']['activity']}*\\n*{location}*\\n\\nВыберите *дату*:", buttons=buttons)
        set_state(user_id, "choosing_date", state["data"])
    
    elif data.startswith("date:"):
        choice = data.split(":")[1]
        if choice == "today":
            work_date = date.today().isoformat()
        else:
            work_date = (date.today() - timedelta(days=1)).isoformat()
        
        state = get_state(user_id)
        state["data"]["work_date"] = work_date
        set_state(user_id, "wait_hours", state["data"])
        
        wa.send_message(to=user_id, text=f"Введите *количество часов* (1-24):")
    
    elif data.startswith("nav:"):
        parts = data.split(":")
        if len(parts) < 3:
            return
        state_key = parts[1]
        try:
            page = int(parts[2])
        except:
            return
        
        state = get_state(user_id)
        
        if state_key == "acts":
            acts = state["data"].get("acts", [])
            send_paginated_buttons(
                to=user_id,
                text="Выберите *вид работы*:",
                items=acts,
                make_button=lambda a: PaginationButton(title=a[1][:20], callback_data=f"act:{a[0]}"),
                state_key="acts",
                page=page,
                back_cb="menu:work"
            )
        elif state_key == "locs":
            locs = state["data"].get("locs", [])
            send_paginated_buttons(
                to=user_id,
                text="Выберите *место*:",
                items=locs,
                make_button=lambda l: PaginationButton(title=l[1][:20], callback_data=f"loc:{l[0]}"),
                state_key="locs",
                page=page,
                back_cb="menu:work"
            )
    
    elif data == "menu:stats":
        wa.send_message(to=user_id, text="📊 Раздел в разработке...")
    
    elif data == "menu:more":
        buttons = [
            Button(title="✏️ Имя", callback_data="menu:name"),
            Button(title="🔙 Назад", callback_data="menu:root"),
        ]
        wa.send_message(to=user_id, text="Доп. меню:", buttons=buttons)
    
    elif data == "menu:name":
        set_state(user_id, "waiting_name")
        wa.send_message(to=user_id, text="Введите новое *Фамилию Имя*:")
    
    else:
        wa.send_message(to=user_id, text=f"❌ Неизвестная команда")

# Webhook
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if verify_token == VERIFY_TOKEN:
            logging.info("✅ Webhook verified")
            return challenge
        else:
            return "Invalid verify token", 403
    
    elif request.method == "POST":
        try:
            data = request.get_json()
            logging.info(f"[WEBHOOK] {data}")
            wa.process_webhook(data)
            return jsonify({"status": "ok"}), 200
        except Exception as e:
            logging.error(f"Error: {e}")
            return jsonify({"status": "error"}), 500

# Запуск
if __name__ == "__main__":
    init_db()
    
    logging.info("🤖 WhatsApp бот запущен!")
    logging.info(f"📡 {SERVER_HOST}:{SERVER_PORT}")
    
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)
