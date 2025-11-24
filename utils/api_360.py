# utils/api_360.py
"""
HTTP-клиент для работы с 360dialog WhatsApp Business API.
Содержит функции для отправки текстовых сообщений, интерактивных кнопок и списков.
"""

import os
import logging
import requests
from typing import List, Dict, Optional
from constants import D360_BASE_URL, HTTP_TIMEOUT

logger = logging.getLogger(__name__)

# Получаем API ключ из переменных окружения
D360_API_KEY = os.getenv("D360_API_KEY")


def _get_headers() -> dict:
    """
    Возвращает заголовки для запросов к 360dialog API.
    
    Returns:
        dict: Словарь с заголовками
    """
    return {
        "D360-API-KEY": D360_API_KEY,
        "Content-Type": "application/json"
    }


def send_text(to: str, text: str) -> bool:
    """
    Отправляет текстовое сообщение пользователю.
    
    Args:
        to: Номер телефона получателя (без +, например: 79991234567)
        text: Текст сообщения (поддерживает WhatsApp форматирование)
    
    Returns:
        bool: True если отправлено успешно, False в случае ошибки
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text
        }
    }
    
    try:
        logger.info(f"📤 Отправка текста → {to}")
        response = requests.post(
            D360_BASE_URL,
            json=payload,
            headers=_get_headers(),
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"✅ Текст отправлен → {to}")
            return True
        else:
            logger.error(f"❌ Ошибка {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Timeout при отправке сообщения → {to}")
        return False
    except Exception as e:
        logger.error(f"❌ Исключение при отправке: {e}", exc_info=True)
        return False


def send_interactive_buttons(to: str, body_text: str, buttons_list: List[Dict[str, str]]) -> bool:
    """
    Отправляет интерактивное сообщение с кнопками (reply buttons).
    
    Args:
        to: Номер телефона получателя
        body_text: Текст сообщения
        buttons_list: Список кнопок, например: [{"id": "BTN_ID", "title": "Кнопка"}, ...]
                     Максимум 3 кнопки (ограничение WhatsApp)
    
    Returns:
        bool: True если отправлено успешно
    """
    # Формируем кнопки в формате 360dialog
    button_components = []
    for btn in buttons_list[:3]:  # Максимум 3 кнопки
        button_components.append({
            "type": "reply",
            "reply": {
                "id": btn["id"],
                "title": btn["title"][:20]  # Максимум 20 символов для title
            }
        })
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": body_text
            },
            "action": {
                "buttons": button_components
            }
        }
    }
    
    try:
        logger.info(f"📤 Отправка кнопок ({len(button_components)} шт) → {to}")
        response = requests.post(
            D360_BASE_URL,
            json=payload,
            headers=_get_headers(),
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"✅ Кнопки отправлены → {to}")
            return True
        else:
            logger.error(f"❌ Ошибка {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Timeout при отправке кнопок → {to}")
        return False
    except Exception as e:
        logger.error(f"❌ Исключение при отправке кнопок: {e}", exc_info=True)
        return False


def send_interactive_list(to: str, body_text: str, section_title: str, rows: List[Dict[str, str]]) -> bool:
    """
    Отправляет интерактивное сообщение со списком (list message).
    
    Args:
        to: Номер телефона получателя
        body_text: Текст сообщения
        section_title: Заголовок секции списка
        rows: Список элементов, например:
              [{"id": "ROW_ID", "title": "Заголовок", "description": "Описание"}, ...]
              description - опционально
    
    Returns:
        bool: True если отправлено успешно
    """
    # Формируем строки списка в формате 360dialog
    list_rows = []
    for row in rows:
        row_data = {
            "id": row["id"],
            "title": row["title"][:24]  # Максимум 24 символа для title
        }
        # Добавляем description если есть
        if "description" in row:
            row_data["description"] = row["description"][:72]  # Максимум 72 символа
        
        list_rows.append(row_data)
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": body_text
            },
            "action": {
                "button": "Выбрать",  # Текст кнопки открытия списка
                "sections": [
                    {
                        "title": section_title,
                        "rows": list_rows
                    }
                ]
            }
        }
    }
    
    try:
        logger.info(f"📤 Отправка списка ({len(list_rows)} элементов) → {to}")
        response = requests.post(
            D360_BASE_URL,
            json=payload,
            headers=_get_headers(),
            timeout=HTTP_TIMEOUT
        )
        
        if response.status_code in [200, 201]:
            logger.info(f"✅ Список отправлен → {to}")
            return True
        else:
            logger.error(f"❌ Ошибка {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error(f"⏱️ Timeout при отправке списка → {to}")
        return False
    except Exception as e:
        logger.error(f"❌ Исключение при отправке списка: {e}", exc_info=True)
        return False
