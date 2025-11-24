# utils/state.py
"""
Управление состоянием пользователей (FSM - Finite State Machine).
"""
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

# ============================================================================
# FSM STATES - Состояния машины состояний
# ============================================================================

class States:
    """Константы состояний FSM для WhatsApp бота"""
    MAIN_MENU = "MAIN_MENU"           # Главное меню
    SELECT_WORK = "SELECT_WORK"       # Выбор типа работы
    SELECT_SHIFT = "SELECT_SHIFT"     # Выбор смены
    SELECT_HOURS = "SELECT_HOURS"     # Выбор количества часов
    CONFIRM_SAVE = "CONFIRM_SAVE"     # Подтверждение сохранения

# Хранилище состояний в памяти (в продакшене лучше использовать Redis)
user_states: Dict[str, Dict[str, Any]] = {}


def get_user_state(user_id: str) -> Dict[str, Any]:
    """
    Получить состояние пользователя.
    
    Args:
        user_id: ID пользователя (номер телефона)
    
    Returns:
        Словарь с состоянием: {"state": "...", "data": {...}}
    """
    if user_id not in user_states:
        user_states[user_id] = {
            "state": None,
            "data": {}
        }
    
    return user_states[user_id]


def set_user_state(user_id: str, state: Optional[str], data: Optional[Dict] = None):
    """
    Установить состояние пользователя.
    
    Args:
        user_id: ID пользователя
        state: Название состояния (например, "waiting_name")
        data: Дополнительные данные состояния
    """
    if user_id not in user_states:
        user_states[user_id] = {
            "state": None,
            "data": {}
        }
    
    user_states[user_id]["state"] = state
    
    if data is not None:
        user_states[user_id]["data"] = data
    
    logger.debug(f"🔄 Состояние {user_id}: {state}")


def update_user_data(user_id: str, key: str, value: Any):
    """
    Обновить данные состояния пользователя.
    
    Args:
        user_id: ID пользователя
        key: Ключ для обновления
        value: Значение
    """
    state = get_user_state(user_id)
    state["data"][key] = value
    logger.debug(f"📝 Обновлены данные {user_id}: {key} = {value}")


def get_user_data(user_id: str, key: str, default: Any = None) -> Any:
    """
    Получить данные из состояния пользователя.
    
    Args:
        user_id: ID пользователя
        key: Ключ данных
        default: Значение по умолчанию
    
    Returns:
        Значение или default
    """
    state = get_user_state(user_id)
    return state["data"].get(key, default)


def clear_user_state(user_id: str):
    """
    Очистить состояние пользователя.
    
    Args:
        user_id: ID пользователя
    """
    user_states[user_id] = {
        "state": None,
        "data": {}
    }
    logger.debug(f"🧹 Состояние {user_id} очищено")


def delete_user_state(user_id: str):
    """
    Полностью удалить состояние пользователя из памяти.
    
    Args:
        user_id: ID пользователя
    """
    if user_id in user_states:
        del user_states[user_id]
        logger.debug(f"🗑️ Состояние {user_id} удалено")


def get_all_states() -> Dict[str, Dict[str, Any]]:
    """
    Получить все состояния (для отладки).
    
    Returns:
        Словарь всех состояний
    """
    return user_states


# ============================================================================
# АЛИАСЫ для соответствия требованиям
# ============================================================================

def set_state(phone: str, state: Optional[str], data: Optional[Dict] = None):
    """Алиас для set_user_state()"""
    return set_user_state(phone, state, data)


def get_state(phone: str) -> Dict[str, Any]:
    """Алиас для get_user_state()"""
    return get_user_state(phone)


def clear_state(phone: str):
    """Алиас для clear_user_state()"""
    return clear_user_state(phone)
