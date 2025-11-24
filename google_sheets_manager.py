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
            ['Дата создания', 'User ID', 'Имя', 'Локация', 'Группа локации', 
             'Вид работы', 'Группа работы', 'Дата работы', 'Часы']
        ]
        
        _sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range='Отчеты!A1:I1',
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
    
    # Создаем новую только если не нашли
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
            loc_grp,
            activity,
            act_grp,
            work_date,
            hours
        ]]
        
        # Добавляем строку
        result = _sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='Отчеты!A2:I2',
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
            report_row[4],  # location_grp
            report_row[5],  # activity
            report_row[6],  # activity_grp
            report_row[7],  # work_date
            report_row[8],  # hours
        ]]
        
        _sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A{row_number}:I{row_number}',
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
    
    count, message = export_reports_to_sheets()
    logger.info(f"📊 {message}")
    
    created, msg = check_and_create_next_month_sheet()
    if created:
        logger.info(f"📅 {msg}")
