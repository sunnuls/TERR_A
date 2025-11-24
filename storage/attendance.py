# storage/attendance.py
"""
Модуль для работы с учетом смен (attendance tracking).
Использует JSON файл data/attendance.json для хранения записей о сменах сотрудников.
"""

import json
import os
from datetime import date
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

# Путь к файлу с данными
DATA_FILE = os.path.join("data", "attendance.json")


def load_data() -> dict:
    """
    Загружает данные из JSON файла.
    
    Returns:
        dict: Словарь с данными пользователей. Если файла нет, возвращает пустой dict.
              Формат: {user_id: [{"date": "YYYY-MM-DD", "shift": "название смены"}, ...]}
    """
    if not os.path.exists(DATA_FILE):
        logger.info(f"Файл {DATA_FILE} не найден, возвращаем пустой словарь")
        return {}
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.info(f"Загружено записей для {len(data)} пользователей")
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка чтения JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"Ошибка загрузки данных: {e}")
        return {}


def save_data(data: dict) -> None:
    """
    Атомарно сохраняет данные в JSON файл.
    Использует временный файл для безопасной записи.
    
    Args:
        data: Словарь с данными для сохранения
    """
    # Создаем директорию если её нет
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    
    # Атомарная запись через временный файл
    temp_file = DATA_FILE + ".tmp"
    
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Замена оригинального файла на временный
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(temp_file, DATA_FILE)
        
        logger.info(f"Данные успешно сохранены в {DATA_FILE}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")
        # Удаляем временный файл в случае ошибки
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise


def save_attendance(user_id: str, date_str: str, shift: str) -> None:
    """
    Сохраняет запись о смене для пользователя.
    
    Args:
        user_id: ID пользователя (номер телефона без +)
        date_str: Дата в формате YYYY-MM-DD
        shift: Название смены
    """
    # Загружаем текущие данные
    data = load_data()
    
    # Создаем массив для пользователя, если его еще нет
    if user_id not in data:
        data[user_id] = []
    
    # Добавляем новую запись
    entry = {
        "date": date_str,
        "shift": shift
    }
    data[user_id].append(entry)
    
    # Сохраняем обновленные данные
    save_data(data)
    
    logger.info(f"Сохранена смена для {user_id}: {date_str} - {shift}")


def get_last_entries(user_id: str, n: int = 3) -> List[dict]:
    """
    Получает последние N записей пользователя.
    
    Args:
        user_id: ID пользователя (номер телефона без +)
        n: Количество последних записей (по умолчанию 3)
    
    Returns:
        list: Список последних записей [{"date": "YYYY-MM-DD", "shift": "..."}, ...]
              Записи отсортированы от новых к старым
    """
    data = load_data()
    
    # Получаем записи пользователя
    user_entries = data.get(user_id, [])
    
    # Сортируем по дате (новые сначала) и берем последние N
    sorted_entries = sorted(user_entries, key=lambda x: x.get("date", ""), reverse=True)
    
    return sorted_entries[:n]

