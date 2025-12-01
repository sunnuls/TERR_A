# google_sheets_manager.py
# -*- coding: utf-8 -*-
"""
Модуль для управления Google Sheets интеграцией
Автоматическое создание таблиц, экспорт отчетов и синхронизация
"""

import os
import logging
from datetime import datetime, date
from typing import Optional, Tuple, List
import calendar
from pathlib import Path
import threading

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Импорт функций БД
import sqlite3
from contextlib import closing

# Настройки
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

OAUTH_CLIENT_JSON = os.getenv("OAUTH_CLIENT_JSON", "oauth_client.json")
TOKEN_JSON_PATH = Path(os.getenv("TOKEN_JSON_PATH", "token.json"))
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
EXPORT_PREFIX = os.getenv("EXPORT_PREFIX", "WorkLog")
DB_PATH = os.path.join(os.getcwd(), "reports_whatsapp.db")

# Глобальные переменные для сервисов
_sheets_service = None
_drive_service = None
_initialized = False
_export_lock = threading.Lock()  # Блокировка для предотвращения одновременных экспортов

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def connect():
    """Подключение к БД"""
    return sqlite3.connect(DB_PATH)


def initialize_google_sheets() -> bool:
    """
    Инициализация подключения к Google Sheets API
    Возвращает True если успешно, False если нет
    """
    global _sheets_service, _drive_service, _initialized
    
    try:
        # Проверяем наличие credentials файла
        if not os.path.exists(OAUTH_CLIENT_JSON):
            logger.warning(f"⚠️ OAuth credentials файл не найден: {OAUTH_CLIENT_JSON}")
            return False
        
        creds = None
        
        # Загружаем существующий токен если есть
        if TOKEN_JSON_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_JSON_PATH), GOOGLE_SCOPES)
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки токена: {e}")
        
        # Если нет валидных credentials, запускаем OAuth flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("🔄 Обновление токена...")
                creds.refresh(Request())
            else:
                logger.info("🔐 Запуск OAuth авторизации...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    OAUTH_CLIENT_JSON, GOOGLE_SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Сохраняем токен
            TOKEN_JSON_PATH.write_text(creds.to_json())
            logger.info("✅ Токен сохранен")
        
        # Создаем сервисы
        _sheets_service = build('sheets', 'v4', credentials=creds)
        _drive_service = build('drive', 'v3', credentials=creds)
        _initialized = True
        
        logger.info("✅ Google Sheets API инициализирован")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации Google Sheets: {e}")
        return False


def is_initialized() -> bool:
    """Проверка инициализации"""
    return _initialized


def create_monthly_sheet(year: int, month: int) -> Tuple[bool, str, str]:
    """
    Создает новую таблицу для указанного месяца
    
    Returns:
        (success, spreadsheet_id, sheet_url)
    """
    if not _initialized:
        return False, "", "Google Sheets не инициализирован"
    
    try:
        # Название таблицы
        month_name = calendar.month_name[month]
        title = f"{EXPORT_PREFIX} - {month_name} {year}"
        
        # Создаем таблицу
        spreadsheet = {
            'properties': {
                'title': title
            },
            'sheets': [{
                'properties': {
                    'title': 'Отчеты',
                    'gridProperties': {
                        'frozenRowCount': 1
                    }
                }
            }]
        }
        
        result = _sheets_service.spreadsheets().create(body=spreadsheet).execute()
        spreadsheet_id = result['spreadsheetId']
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        # Добавляем заголовки
        headers = [
            ['Дата создания', 'User ID', 'Имя', 'Локация', 
             'Вид работы', 'Дата работы', 'Часы']
        ]
        
        _sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Отчеты!A1:G1',
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()
        
        # Форматируем заголовки (жирный шрифт) - опционально
        try:
            requests = [{
                'repeatCell': {
                    'range': {
                        'sheetId': 0,
                        'startRowIndex': 0,
                        'endRowIndex': 1
                    },
                    'cell': {
                        'userEnteredFormat': {
                            'textFormat': {'bold': True},
                            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                        }
                    },
                    'fields': 'userEnteredFormat(textFormat,backgroundColor)'
                }
            }]
            
            _sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={'requests': requests}
            ).execute()
        except Exception as e:
            logger.warning(f"⚠️ Не удалось отформатировать заголовки: {e}")
        
        # Перемещаем в папку если указана
        if DRIVE_FOLDER_ID and DRIVE_FOLDER_ID.strip():
            try:
                # Получаем текущие parents
                file_metadata = _drive_service.files().get(
                    fileId=spreadsheet_id,
                    fields='parents'
                ).execute()
                
                previous_parents = ",".join(file_metadata.get('parents', []))
                
                # Перемещаем в целевую папку и удаляем из корня
                _drive_service.files().update(
                    fileId=spreadsheet_id,
                    addParents=DRIVE_FOLDER_ID,
                    removeParents=previous_parents,
                    fields='id, parents'
                ).execute()
                
                logger.info(f"✅ Таблица перемещена в папку {DRIVE_FOLDER_ID}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось переместить в папку: {e}")
        
        # Сохраняем в БД
        with connect() as con, closing(con.cursor()) as c:
            c.execute("""
                INSERT OR REPLACE INTO monthly_sheets (year, month, spreadsheet_id, sheet_url, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (year, month, spreadsheet_id, sheet_url, datetime.now().isoformat()))
            con.commit()
        
        logger.info(f"✅ Создана таблица: {title}")
        logger.info(f"📊 URL: {sheet_url}")
        
        return True, spreadsheet_id, sheet_url
        
    except HttpError as e:
        logger.error(f"❌ HTTP ошибка при создании таблицы: {e}")
        return False, "", str(e)
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблицы: {e}")
        return False, "", str(e)


def get_or_create_monthly_sheet(year: int, month: int) -> Tuple[bool, str, str]:
    """
    Получает существующую или создает новую таблицу для месяца
    
    Returns:
        (success, spreadsheet_id, sheet_url)
    """
    # Проверяем в БД
    with connect() as con, closing(con.cursor()) as c:
        row = c.execute(
            "SELECT spreadsheet_id, sheet_url FROM monthly_sheets WHERE year=? AND month=?",
            (year, month)
        ).fetchone()
        
        if row:
            logger.info(f"ℹ️ Таблица для {year}-{month:02d} уже существует")
            return True, row[0], row[1]
    
    # Если в БД нет, ищем в Google Drive по имени
    try:
        month_name = calendar.month_name[month]
        title = f"{EXPORT_PREFIX} - {month_name} {year}"
        
        q = f"name = '{title}' and trashed = false"
        if DRIVE_FOLDER_ID:
            q += f" and '{DRIVE_FOLDER_ID}' in parents"
            
        results = _drive_service.files().list(
            q=q, 
            fields="files(id, webViewLink)",
            orderBy="createdTime desc"
        ).execute()
        
        files = results.get('files', [])
        if files:
            spreadsheet_id = files[0]['id']
            sheet_url = files[0]['webViewLink']
            
            logger.info(f"ℹ️ Найдена существующая таблица в Drive: {title}")
            
            # Сохраняем в БД для будущего использования
            with connect() as con, closing(con.cursor()) as c:
                c.execute("""
                    INSERT OR REPLACE INTO monthly_sheets (year, month, spreadsheet_id, sheet_url, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (year, month, spreadsheet_id, sheet_url, datetime.now().isoformat()))
                con.commit()
                
            return True, spreadsheet_id, sheet_url
            
    except Exception as e:
        logger.warning(f"⚠️ Ошибка поиска таблицы в Drive: {e}")

    # Создаем новую только если не нашли ни в БД, ни в Drive
    logger.info(f"📝 Создаю новую таблицу для {year}-{month:02d}")
    return create_monthly_sheet(year, month)


def export_report_to_sheet(report_id: int) -> bool:
    """
    Экспортирует один отчет в Google Sheets
    """
    if not _initialized:
        logger.warning("⚠️ Google Sheets не инициализирован")
        return False
    
    try:
        # Получаем отчет из БД
        with connect() as con, closing(con.cursor()) as c:
            row = c.execute("""
                SELECT id, created_at, user_id, reg_name, location, location_grp,
                       activity, activity_grp, work_date, hours
                FROM reports WHERE id=?
            """, (report_id,)).fetchone()
            
            if not row:
                logger.error(f"❌ Отчет {report_id} не найден")
                return False
            
            # Проверяем, не экспортирован ли уже
            existing = c.execute(
                "SELECT row_number FROM google_exports WHERE report_id=?",
                (report_id,)
            ).fetchone()
            
            if existing:
                logger.info(f"ℹ️ Отчет {report_id} уже экспортирован")
                return True
        
        # Парсим данные
        rid, created_at, user_id, reg_name, location, loc_grp, activity, act_grp, work_date, hours = row
        
        # Определяем месяц и год
        work_date_obj = datetime.fromisoformat(work_date).date()
        year, month = work_date_obj.year, work_date_obj.month
        
        # Получаем или создаем таблицу
        success, spreadsheet_id, sheet_url = get_or_create_monthly_sheet(year, month)
        if not success:
            return False
        
        # Подготавливаем данные для вставки
        values = [[
            created_at,
            user_id,
            reg_name or "",
            location,
            activity,
            work_date,
            hours
        ]]
        
        # Добавляем строку
        result = _sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='Отчеты!A2:G2',
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body={'values': values}
        ).execute()
        
        # Получаем номер строки
        updated_range = result.get('updates', {}).get('updatedRange', '')
        row_number = int(updated_range.split('!')[1].split(':')[0][1:]) if updated_range else 0
        
        # Сохраняем в БД
        with connect() as con, closing(con.cursor()) as c:
            c.execute("""
                INSERT INTO google_exports (report_id, spreadsheet_id, sheet_name, row_number, exported_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (report_id, spreadsheet_id, 'Отчеты', row_number, 
                  datetime.now().isoformat(), datetime.now().isoformat()))
            con.commit()
        
        logger.info(f"✅ Отчет {report_id} экспортирован в строку {row_number}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта отчета {report_id}: {e}")
        return False


def export_reports_to_sheets() -> Tuple[int, str]:
    """
    Экспортирует все неэкспортированные отчеты
    
    Returns:
        (count, message)
    """
    # Проверяем блокировку - если уже идет экспорт, не запускаем новый
    if not _export_lock.acquire(blocking=False):
        logger.warning("⚠️ Экспорт уже выполняется, пропускаем")
        return 0, "Экспорт уже выполняется"
    
    try:
        if not _initialized:
            if not initialize_google_sheets():
                return 0, "Google Sheets не настроен"
        
        # Получаем все отчеты, которые еще не экспортированы
        with connect() as con, closing(con.cursor()) as c:
            rows = c.execute("""
                SELECT r.id FROM reports r
                LEFT JOIN google_exports ge ON r.id = ge.report_id
                WHERE ge.report_id IS NULL
                ORDER BY r.created_at
            """).fetchall()
        
        if not rows:
            return 0, "Все отчеты уже экспортированы"
        
        count = 0
        for (report_id,) in rows:
            if export_report_to_sheet(report_id):
                count += 1
        
        return count, f"Экспортировано отчетов: {count}"
        
    except Exception as e:
        logger.error(f"❌ Ошибка массового экспорта: {e}")
        return 0, f"Ошибка: {str(e)}"
    finally:
        _export_lock.release()


def sync_report_update(report_id: int) -> bool:
    """
    Обновляет запись в Google Sheets при изменении отчета
    """
    if not _initialized:
        return False
    
    try:
        # Получаем информацию об экспорте
        with connect() as con, closing(con.cursor()) as c:
            export_row = c.execute("""
                SELECT spreadsheet_id, sheet_name, row_number
                FROM google_exports WHERE report_id=?
            """, (report_id,)).fetchone()
            
            if not export_row:
                # Отчет не экспортирован, экспортируем
                return export_report_to_sheet(report_id)
            
            spreadsheet_id, sheet_name, row_number = export_row
            
            # Получаем обновленные данные отчета
            report_row = c.execute("""
                SELECT created_at, user_id, reg_name, location, location_grp,
                       activity, activity_grp, work_date, hours
                FROM reports WHERE id=?
            """, (report_id,)).fetchone()
            
            if not report_row:
                return False
        
        # Обновляем строку в таблице
        values = [[
            report_row[0],  # created_at
            report_row[1],  # user_id
            report_row[2] or "",  # reg_name
            report_row[3],  # location
            report_row[5],  # activity
            report_row[7],  # work_date
            report_row[8],  # hours
        ]]
        
        _sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A{row_number}:G{row_number}',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        
        # Обновляем timestamp
        with connect() as con, closing(con.cursor()) as c:
            c.execute(
                "UPDATE google_exports SET last_updated=? WHERE report_id=?",
                (datetime.now().isoformat(), report_id)
            )
            con.commit()
        
        logger.info(f"✅ Отчет {report_id} обновлен в Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления отчета {report_id}: {e}")
        return False


def sync_report_delete(report_id: int) -> bool:
    """
    Удаляет запись из Google Sheets при удалении отчета
    """
    if not _initialized:
        return False
    
    try:
        # Получаем информацию об экспорте
        with connect() as con, closing(con.cursor()) as c:
            export_row = c.execute("""
                SELECT spreadsheet_id, sheet_name, row_number
                FROM google_exports WHERE report_id=?
            """, (report_id,)).fetchone()
            
            if not export_row:
                return True  # Не экспортирован, ничего делать не нужно
            
            spreadsheet_id, sheet_name, row_number = export_row
        
        # Получаем sheet_id
        spreadsheet = _sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        
        sheet_id = None
        for sheet in spreadsheet['sheets']:
            if sheet['properties']['title'] == sheet_name:
                sheet_id = sheet['properties']['sheetId']
                break
        
        if sheet_id is None:
            logger.error(f"❌ Лист {sheet_name} не найден")
            return False
        
        # Удаляем строку
        requests = [{
            'deleteDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': row_number - 1,
                    'endIndex': row_number
                }
            }
        }]
        
        _sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': requests}
        ).execute()
        
        # Удаляем из БД
        with connect() as con, closing(con.cursor()) as c:
            c.execute("DELETE FROM google_exports WHERE report_id=?", (report_id,))
            con.commit()
        
        logger.info(f"✅ Отчет {report_id} удален из Google Sheets")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления отчета {report_id}: {e}")
        return False


def check_and_create_next_month_sheet() -> Tuple[bool, str]:
    """
    Проверяет и создает таблицу для следующего месяца если нужно
    """
    if not _initialized:
        return False, ""
    
    try:
        today = date.today()
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        
        # Проверяем существование
        with connect() as con, closing(con.cursor()) as c:
            exists = c.execute(
                "SELECT 1 FROM monthly_sheets WHERE year=? AND month=?",
                (next_year, next_month)
            ).fetchone()
            
            if exists:
                return False, ""
        
        # Создаем
        success, _, url = create_monthly_sheet(next_year, next_month)
        if success:
            month_name = calendar.month_name[next_month]
            return True, f"Создана таблица для {month_name} {next_year}: {url}"
        
        return False, ""
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблицы следующего месяца: {e}")
        return False, ""


def scheduled_export():
    """
    Функция для запланированного экспорта (вызывается по расписанию)
    """
    logger.info("⏰ Запуск запланированного экспорта...")
    
    if not _initialized:
        if not initialize_google_sheets():
            logger.error("❌ Не удалось инициализировать Google Sheets")
            return
    
    created, msg = check_and_create_next_month_sheet()
    if created:
        logger.info(f"📅 {msg}")
    
    # Экспорт отчетов бригадиров
    brig_count, brig_msg = export_brigadier_reports()
    if brig_count > 0:
        logger.info(f"👷 {brig_msg}")


# -----------------------------
# Функции для бригадиров
# -----------------------------

BRIGADIER_FOLDER_ID = os.getenv("BRIGADIER_FOLDER_ID", "")

def create_brigadier_monthly_sheet(year: int, month: int) -> Tuple[bool, str, str]:
    """
    Создает таблицу для бригадиров
    """
    if not _initialized:
        return False, "", "Google Sheets не инициализирован"
    
    try:
        month_name = calendar.month_name[month]
        title = f"Бригадиры - {month_name} {year}"
        
        spreadsheet = {
            'properties': {'title': title},
            'sheets': [{'properties': {'title': 'Отчеты', 'gridProperties': {'frozenRowCount': 1}}}]
        }
        
        result = _sheets_service.spreadsheets().create(body=spreadsheet).execute()
        spreadsheet_id = result['spreadsheetId']
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        headers = [['Дата создания', 'User ID', 'Имя', 'Тип работы', 'Дата работы', 'Ряды', 'Поле', 'Сетки', 'Люди']]
        
        _sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Отчеты!A1:I1',
            valueInputOption='RAW',
            body={'values': headers}
        ).execute()
        
        # Перемещаем в папку бригадиров
        target_folder = BRIGADIER_FOLDER_ID or DRIVE_FOLDER_ID
        if target_folder:
            try:
                file_metadata = _drive_service.files().get(fileId=spreadsheet_id, fields='parents').execute()
                previous_parents = ",".join(file_metadata.get('parents', []))
                _drive_service.files().update(
                    fileId=spreadsheet_id,
                    addParents=target_folder,
                    removeParents=previous_parents,
                    fields='id, parents'
                ).execute()
            except Exception as e:
                logger.warning(f"⚠️ Не удалось переместить таблицу бригадиров: {e}")
        
        # Сохраняем в БД (используем ту же таблицу monthly_sheets, но добавляем метку типа или просто ищем по ID, 
        # но лучше создать отдельную таблицу для трекинга листов бригадиров, или просто искать по имени/папке.
        # Для простоты пока не будем сохранять в monthly_sheets, а будем искать каждый раз или кэшировать.
        # Или добавим колонку type в monthly_sheets. 
        # Но чтобы не усложнять схему, просто будем создавать/искать по имени.)
        
        return True, spreadsheet_id, sheet_url
    except Exception as e:
        logger.error(f"❌ Ошибка создания таблицы бригадиров: {e}")
        return False, "", str(e)

def get_or_create_brigadier_sheet(year: int, month: int) -> Tuple[bool, str, str]:
    """Получает или создает таблицу бригадиров"""
    # Здесь упрощенная логика: ищем таблицу с нужным именем в нужной папке
    # Это медленнее, но не требует изменений схемы monthly_sheets
    try:
        month_name = calendar.month_name[month]
        title = f"Бригадиры - {month_name} {year}"
        q = f"name = '{title}' and trashed = false"
        if BRIGADIER_FOLDER_ID:
            q += f" and '{BRIGADIER_FOLDER_ID}' in parents"
            
        results = _drive_service.files().list(q=q, fields="files(id, webViewLink)").execute()
        files = results.get('files', [])
        
        if files:
            return True, files[0]['id'], files[0]['webViewLink']
        
        return create_brigadier_monthly_sheet(year, month)
    except Exception as e:
        logger.error(f"❌ Ошибка поиска таблицы бригадиров: {e}")
        return False, "", ""

def export_brigadier_report_to_sheet(report_id: int) -> bool:
    """Экспорт отчета бригадира"""
    if not _initialized: return False
    
    try:
        with connect() as con, closing(con.cursor()) as c:
            row = c.execute("""
                SELECT id, timestamp, user_id, username, work_type, work_date, rows, field, bags, workers
                FROM brigadier_reports WHERE id=?
            """, (report_id,)).fetchone()
            
            if not row: return False
            
            # Проверка экспорта
            existing = c.execute("SELECT row_number FROM brigadier_google_exports WHERE report_id=?", (report_id,)).fetchone()
            if existing: return True
            
            rid, ts, uid, uname, wtype, wdate, rows, field, bags, workers = row
            
            # Дата работы
            if wdate:
                wdate_obj = datetime.fromisoformat(wdate).date()
            else:
                wdate_obj = datetime.fromisoformat(ts).date()
                wdate = wdate_obj.isoformat()
            
            year, month = wdate_obj.year, wdate_obj.month
            
            success, spreadsheet_id, sheet_url = get_or_create_brigadier_sheet(year, month)
            if not success: return False
            
            values = [[ts, uid, uname, wtype, wdate, rows, field, bags, workers]]
            
            result = _sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range='Отчеты!A2:I2',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': values}
            ).execute()
            
            updated_range = result.get('updates', {}).get('updatedRange', '')
            row_number = int(updated_range.split('!')[1].split(':')[0][1:]) if updated_range else 0
            
            c.execute("""
                INSERT INTO brigadier_google_exports (report_id, spreadsheet_id, sheet_name, row_number, exported_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (report_id, spreadsheet_id, 'Отчеты', row_number, datetime.now().isoformat(), datetime.now().isoformat()))
            con.commit()
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта отчета бригадира {report_id}: {e}")
        return False

def export_brigadier_reports() -> Tuple[int, str]:
    """Массовый экспорт отчетов бригадиров"""
    if not _initialized: return 0, "Google Sheets не инициализирован"
    
    try:
        with connect() as con, closing(con.cursor()) as c:
            rows = c.execute("""
                SELECT r.id FROM brigadier_reports r
                LEFT JOIN brigadier_google_exports ge ON r.id = ge.report_id
                WHERE ge.report_id IS NULL
                ORDER BY r.timestamp
            """).fetchall()
        
        if not rows: return 0, "Все отчеты бригадиров экспортированы"
        
        count = 0
        for (report_id,) in rows:
            if export_brigadier_report_to_sheet(report_id):
                count += 1
        return count, f"Экспортировано отчетов бригадиров: {count}"
    except Exception as e:
        logger.error(f"❌ Ошибка массового экспорта бригадиров: {e}")
        return 0, str(e)

def delete_all_files_in_folder() -> Tuple[int, str]:
    """
    Удаляет ВСЕ файлы в целевой папке Google Drive.
    Используется для полного сброса.
    """
    if not _initialized:
        if not initialize_google_sheets():
            return 0, "Google Sheets не инициализирован"
            
    if not DRIVE_FOLDER_ID:
        return 0, "DRIVE_FOLDER_ID не настроен"
        
    try:
        # Ищем все файлы в папке
        q = f"'{DRIVE_FOLDER_ID}' in parents and trashed = false"
        results = _drive_service.files().list(q=q, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            return 0, "Папка пуста"
            
        count = 0
        for f in files:
            try:
                _drive_service.files().delete(fileId=f['id']).execute()
                logger.info(f"🗑 Удален файл: {f['name']} ({f['id']})")
                count += 1
            except Exception as e:
                logger.error(f"❌ Ошибка удаления файла {f['name']}: {e}")
                
        return count, f"Удалено файлов: {count}"
        
    except Exception as e:
        logger.error(f"❌ Ошибка очистки папки: {e}")
        return 0, str(e)
