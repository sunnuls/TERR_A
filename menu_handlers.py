# menu_handlers.py
"""
Обработчики меню и логика взаимодействия с пользователем.
Содержит функции для отправки меню, обработки выбора смен и статистики.
"""

import logging
from datetime import date
from typing import Optional
from utils.api_360 import send_text, send_interactive_buttons, send_interactive_list
from storage.attendance import save_attendance, get_last_entries
from constants import (
    BTN_FILL_TODAY, BTN_FILL_RANGE, BTN_MY_STATUS,
    SHIFT_DAY, SHIFT_NIGHT, SHIFT_OFF, SHIFT_NAMES,
    MSG_MAIN_MENU, MSG_SHIFT_SELECT, MSG_SHIFT_SAVED, 
    MSG_RANGE_COMING_SOON, MSG_NO_RECORDS
)

logger = logging.getLogger(__name__)


def send_main_menu(to: str) -> bool:
    """
    Отправляет главное меню с интерактивными кнопками.
    
    Args:
        to: Номер телефона получателя
    
    Returns:
        bool: True если отправлено успешно
    """
    # Временно отправляем текстовое сообщение для теста
    logger.info(f"📋 Отправка главного меню → {to}")
    return send_text(to, f"{MSG_MAIN_MENU}\n\n1️⃣ Заполнить за сегодня\n2️⃣ Заполнить за период\n3️⃣ Мой статус")
    
    # buttons = [
    #     {"id": BTN_FILL_TODAY, "title": "Заполнить за сегодня"},
    #     {"id": BTN_FILL_RANGE, "title": "Заполнить за период"},
    #     {"id": BTN_MY_STATUS, "title": "Мой статус"}
    # ]
    # return send_interactive_buttons(to, MSG_MAIN_MENU, buttons)


def send_shift_list(to: str) -> bool:
    """
    Отправляет интерактивный список для выбора смены.
    
    Args:
        to: Номер телефона получателя
    
    Returns:
        bool: True если отправлено успешно
    """
    rows = [
        {"id": SHIFT_DAY, "title": SHIFT_NAMES[SHIFT_DAY]},
        {"id": SHIFT_NIGHT, "title": SHIFT_NAMES[SHIFT_NIGHT]},
        {"id": SHIFT_OFF, "title": SHIFT_NAMES[SHIFT_OFF]}
    ]
    
    logger.info(f"⏰ Отправка списка смен → {to}")
    return send_interactive_list(to, MSG_SHIFT_SELECT, "Смены", rows)


def handle_main_menu_button(to: str, button_id: str) -> bool:
    """
    Обрабатывает нажатие кнопки главного меню.
    
    Args:
        to: Номер телефона пользователя
        button_id: ID нажатой кнопки
    
    Returns:
        bool: True если обработано успешно
    """
    logger.info(f"🔘 Обработка кнопки главного меню: {button_id} от {to}")
    
    if button_id == BTN_FILL_TODAY:
        # Показываем список смен для заполнения за сегодня
        return send_shift_list(to)
    
    elif button_id == BTN_FILL_RANGE:
        # Пока не реализовано - отправляем заглушку
        return send_text(to, MSG_RANGE_COMING_SOON)
    
    elif button_id == BTN_MY_STATUS:
        # Показываем последние 3 записи пользователя
        return show_user_status(to)
    
    else:
        logger.warning(f"⚠️ Неизвестная кнопка главного меню: {button_id}")
        return send_text(to, "Неизвестная команда. Попробуйте снова.")


def handle_shift_selection(to: str, shift_id: str, title: Optional[str] = None) -> bool:
    """
    Обрабатывает выбор смены из списка.
    
    Args:
        to: Номер телефона пользователя
        shift_id: ID выбранной смены (SHIFT_DAY, SHIFT_NIGHT, SHIFT_OFF)
        title: Название выбранной смены (опционально, для логирования)
    
    Returns:
        bool: True если обработано успешно
    """
    logger.info(f"✅ Выбор смены: {shift_id} ({title or 'N/A'}) от {to}")
    
    # Проверяем что это корректная смена
    if shift_id not in SHIFT_NAMES:
        logger.warning(f"⚠️ Неизвестный ID смены: {shift_id}")
        return send_text(to, "Неизвестная смена. Попробуйте снова.")
    
    # Получаем название смены и текущую дату
    shift_name = SHIFT_NAMES[shift_id]
    today = date.today().isoformat()  # Формат: YYYY-MM-DD
    
    # Сохраняем запись о смене
    try:
        save_attendance(to, today, shift_name)
        logger.info(f"💾 Смена сохранена: {to} / {today} / {shift_name}")
        return send_text(to, MSG_SHIFT_SAVED)
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения смены: {e}", exc_info=True)
        return send_text(to, "Ошибка при сохранении. Попробуйте позже.")


def show_user_status(to: str) -> bool:
    """
    Показывает последние 3 записи пользователя.
    
    Args:
        to: Номер телефона пользователя
    
    Returns:
        bool: True если отправлено успешно
    """
    logger.info(f"📊 Запрос статуса от {to}")
    
    # Получаем последние 3 записи
    entries = get_last_entries(to, n=3)
    
    if not entries:
        return send_text(to, MSG_NO_RECORDS)
    
    # Формируем текст с записями
    lines = ["Ваши последние записи:"]
    for entry in entries:
        entry_date = entry.get("date", "Н/Д")
        entry_shift = entry.get("shift", "Н/Д")
        lines.append(f"{entry_date} — {entry_shift}")
    
    status_text = "\n".join(lines)
    
    logger.info(f"📤 Отправка статуса ({len(entries)} записей) → {to}")
    return send_text(to, status_text)
