# utils/sheets.py
"""
Интеграция с Google Sheets для сохранения данных.
Использует gspread и oauth2client для авторизации.
"""
import logging
import base64
import json
import os
import tempfile
from datetime import datetime
from typing import Optional

from oauth2client.service_account import ServiceAccountCredentials
import gspread

from config import SHEETS_CREDENTIALS, SHEET_ID, SHEETS_ENABLED

logger = logging.getLogger(__name__)

# Глобальные переменные для хранения подключения
_spreadsheet = None
_worksheet = None
_sheets_initialized = False

# Область доступа для Google Sheets API
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]


def init_sheets() -> bool:
    """
    Инициализация подключения к Google Sheets.
    
    1. Загружает JSON ключи из переменной окружения SHEETS_CREDENTIALS (base64)
    2. Авторизуется через ServiceAccountCredentials
    3. Открывает таблицу по SHEET_ID
    4. Выбирает лист "Данные" или создаёт его
    
    Returns:
        bool: True если инициализация успешна
    """
    global _spreadsheet, _worksheet, _sheets_initialized
    
    # Проверка, включена ли интеграция
    if not SHEETS_ENABLED:
        logger.info("[SHEETS] ⚠️ Google Sheets интеграция отключена (SHEETS_ENABLED=false)")
        return False
    
    # Проверка наличия обязательных параметров
    if not SHEETS_CREDENTIALS:
        logger.warning("[SHEETS] ⚠️ SHEETS_CREDENTIALS не указан в .env")
        return False
    
    if not SHEET_ID:
        logger.warning("[SHEETS] ⚠️ SHEET_ID не указан в .env")
        return False
    
    try:
        logger.info("[SHEETS] 🔄 Инициализация подключения к Google Sheets...")
        
        # Шаг 1: Загрузка и декодирование credentials
        credentials_dict = _load_credentials()
        if not credentials_dict:
            return False
        
        # Шаг 2: Авторизация
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(
            credentials_dict,
            SCOPES
        )
        
        logger.info("[SHEETS] ✓ Авторизация выполнена успешно")
        
        # Шаг 3: Подключение к Google Sheets
        client = gspread.authorize(credentials)
        logger.info("[SHEETS] ✓ Подключение к Google Sheets установлено")
        
        # Шаг 4: Открытие таблицы по ID
        try:
            _spreadsheet = client.open_by_key(SHEET_ID)
            logger.info(f"[SHEETS] ✓ Таблица открыта: '{_spreadsheet.title}'")
        except gspread.SpreadsheetNotFound:
            logger.error(f"[SHEETS] ❌ Таблица с ID '{SHEET_ID}' не найдена")
            logger.error("[SHEETS] Проверьте SHEET_ID в .env и права доступа service account")
            return False
        except Exception as e:
            logger.error(f"[SHEETS] ❌ Ошибка открытия таблицы: {e}")
            return False
        
        # Шаг 5: Выбор или создание листа "Данные"
        try:
            _worksheet = _spreadsheet.worksheet("Данные")
            logger.info("[SHEETS] ✓ Лист 'Данные' найден")
        except gspread.WorksheetNotFound:
            logger.info("[SHEETS] Лист 'Данные' не найден, создаю новый...")
            _worksheet = _spreadsheet.add_worksheet(title="Данные", rows=1000, cols=10)
            
            # Добавляем заголовки
            headers = ["Дата и время", "Телефон", "Работа", "Смена", "Часов"]
            _worksheet.append_row(headers)
            logger.info("[SHEETS] ✓ Лист 'Данные' создан с заголовками")
        
        # Проверка наличия заголовков
        _ensure_headers()
        
        _sheets_initialized = True
        logger.info("[SHEETS] ✅ Инициализация Google Sheets завершена успешно")
        return True
        
    except Exception as e:
        logger.error(f"[SHEETS] ❌ Критическая ошибка инициализации: {e}", exc_info=True)
        _sheets_initialized = False
        return False


def _load_credentials() -> Optional[dict]:
    """
    Загружает credentials из base64 строки или файла.
    
    Returns:
        dict или None: Словарь с credentials или None при ошибке
    """
    try:
        # Вариант 1: SHEETS_CREDENTIALS содержит base64 encoded JSON
        if SHEETS_CREDENTIALS.startswith("{"):
            # Прямой JSON
            logger.info("[SHEETS] Загрузка credentials из JSON строки")
            return json.loads(SHEETS_CREDENTIALS)
        
        elif len(SHEETS_CREDENTIALS) > 100 and not SHEETS_CREDENTIALS.endswith(".json"):
            # Base64 encoded
            logger.info("[SHEETS] Декодирование credentials из base64")
            decoded = base64.b64decode(SHEETS_CREDENTIALS)
            return json.loads(decoded)
        
        else:
            # Вариант 2: SHEETS_CREDENTIALS содержит путь к файлу
            if os.path.exists(SHEETS_CREDENTIALS):
                logger.info(f"[SHEETS] Загрузка credentials из файла: {SHEETS_CREDENTIALS}")
                with open(SHEETS_CREDENTIALS, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.error(f"[SHEETS] ❌ Файл credentials не найден: {SHEETS_CREDENTIALS}")
                return None
                
    except base64.binascii.Error as e:
        logger.error(f"[SHEETS] ❌ Ошибка декодирования base64: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"[SHEETS] ❌ Ошибка парсинга JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"[SHEETS] ❌ Ошибка загрузки credentials: {e}", exc_info=True)
        return None


def _ensure_headers():
    """
    Проверяет наличие заголовков в таблице и добавляет их при необходимости.
    """
    try:
        # Получаем первую строку
        first_row = _worksheet.row_values(1)
        
        if not first_row or first_row[0] != "Дата и время":
            # Заголовков нет, добавляем
            headers = ["Дата и время", "Телефон", "Работа", "Смена", "Часов"]
            
            if first_row:
                # Если есть данные, вставляем заголовки перед ними
                _worksheet.insert_row(headers, index=1)
                logger.info("[SHEETS] ✓ Заголовки добавлены в начало таблицы")
            else:
                # Таблица пустая, просто добавляем заголовки
                _worksheet.append_row(headers)
                logger.info("[SHEETS] ✓ Заголовки добавлены в пустую таблицу")
                
    except Exception as e:
        logger.error(f"[SHEETS] ⚠️ Ошибка проверки заголовков: {e}")


def save_entry(phone: str, work: str, shift: str, hours: str) -> bool:
    """
    Сохранить запись о работе пользователя в Google Sheets.
    
    Записывает новую строку: [дата_время, телефон, работа, смена, часы]
    
    Args:
        phone: Номер телефона пользователя (например, "79991234567")
        work: Тип работы (например, "Поле", "Кабачок")
        shift: Смена (например, "8-16", "16-00")
        hours: Количество часов (например, "4", "6", "8", "12")
    
    Returns:
        bool: True если сохранение успешно
    """
    # Валидация входных данных
    if not phone or not isinstance(phone, str):
        logger.error(f"[SHEETS] ❌ Невалидный параметр phone: {phone}")
        return False
    
    if not work or not isinstance(work, str):
        logger.error(f"[SHEETS] ❌ Невалидный параметр work: {work}")
        return False
    
    if not shift or not isinstance(shift, str):
        logger.error(f"[SHEETS] ❌ Невалидный параметр shift: {shift}")
        return False
    
    if not hours or not isinstance(hours, str):
        logger.error(f"[SHEETS] ❌ Невалидный параметр hours: {hours}")
        return False
    
    # Проверка инициализации
    if not _sheets_initialized or not _worksheet:
        logger.warning("[SHEETS] ⚠️ Google Sheets не инициализированы, данные будут только залогированы")
        _log_entry_fallback(phone, work, shift, hours)
        return False
    
    try:
        # Форматируем дату и время
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Подготавливаем строку данных
        row = [timestamp, phone, work, shift, hours]
        
        logger.info(f"[SHEETS] 📝 Сохранение записи в Google Sheets:")
        logger.info(f"[SHEETS]   ▸ Время: {timestamp}")
        logger.info(f"[SHEETS]   ▸ Телефон: {phone}")
        logger.info(f"[SHEETS]   ▸ Работа: {work}")
        logger.info(f"[SHEETS]   ▸ Смена: {shift}")
        logger.info(f"[SHEETS]   ▸ Часов: {hours}")
        
        # Записываем в таблицу
        _worksheet.append_row(row, value_input_option='USER_ENTERED')
        
        logger.info(f"[SHEETS] ✅ Запись успешно сохранена в Google Sheets")
        return True
        
    except gspread.exceptions.APIError as e:
        logger.error(f"[SHEETS] ❌ API ошибка Google Sheets: {e}", exc_info=True)
        logger.error(f"[SHEETS] Детали: {e.response.text if hasattr(e, 'response') else 'нет деталей'}")
        _log_entry_fallback(phone, work, shift, hours)
        return False
        
    except Exception as e:
        logger.error(f"[SHEETS] ❌ Ошибка при сохранении записи: {e}", exc_info=True)
        _log_entry_fallback(phone, work, shift, hours)
        return False


def _log_entry_fallback(phone: str, work: str, shift: str, hours: str):
    """
    Запасной вариант: логирование данных при невозможности сохранить в Google Sheets.
    
    Args:
        phone: Номер телефона
        work: Тип работы
        shift: Смена
        hours: Количество часов
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.warning("[SHEETS] ⚠️ Запись в Google Sheets невозможна, данные сохранены в лог:")
    logger.info(f"[FALLBACK] {timestamp} | {phone} | {work} | {shift} | {hours}")
    
    # Также можно сохранить в локальный файл
    try:
        with open('sheets_fallback.log', 'a', encoding='utf-8') as f:
            f.write(f"{timestamp},{phone},{work},{shift},{hours}\n")
        logger.info("[SHEETS] ✓ Данные сохранены в sheets_fallback.log")
    except Exception as e:
        logger.error(f"[SHEETS] ❌ Ошибка записи в fallback файл: {e}")


def get_sheet_url() -> Optional[str]:
    """
    Получить URL открытой таблицы.
    
    Returns:
        str или None: URL таблицы или None если не инициализировано
    """
    if _spreadsheet:
        return _spreadsheet.url
    return None


def is_initialized() -> bool:
    """
    Проверить, инициализировано ли подключение к Google Sheets.
    
    Returns:
        bool: True если инициализировано
    """
    return _sheets_initialized


def get_stats() -> dict:
    """
    Получить статистику по записям (опционально).
    
    Returns:
        dict: Статистика
    """
    if not _sheets_initialized or not _worksheet:
        return {"status": "not_initialized"}
    
    try:
        # Получаем все значения (кроме заголовка)
        all_values = _worksheet.get_all_values()[1:]  # Пропускаем заголовок
        
        return {
            "status": "ok",
            "total_records": len(all_values),
            "sheet_title": _worksheet.title,
            "spreadsheet_title": _spreadsheet.title,
            "url": _spreadsheet.url
        }
    except Exception as e:
        logger.error(f"[SHEETS] ❌ Ошибка получения статистики: {e}")
        return {"status": "error", "message": str(e)}


# Устаревшие функции (для совместимости)
def export_to_sheet(data: list) -> bool:
    """
    Экспортировать данные в Google Sheets.
    УСТАРЕЛО: Используйте save_entry()
    """
    logger.warning("⚠️ export_to_sheet устарел, используйте save_entry()")
    return False


def read_from_sheet(sheet_range: str) -> list:
    """
    Прочитать данные из Google Sheets.
    УСТАРЕЛО: Используйте get_stats() или прямой доступ через gspread
    """
    logger.warning("⚠️ read_from_sheet устарел")
    return []


def update_sheet_row(row_number: int, data: list) -> bool:
    """
    Обновить строку в Google Sheets.
    УСТАРЕЛО: Используйте gspread API напрямую
    """
    logger.warning("⚠️ update_sheet_row устарел")
    return False
