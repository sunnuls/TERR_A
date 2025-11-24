#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки работы 360dialog Cloud API.

Использование:
    python test_360dialog_api.py

Перед запуском:
    1. Настройте .env файл с вашими API ключами
    2. Замените TEST_PHONE на реальный номер телефона
"""
import sys
import time
from bot import send_message, send_buttons, send_list
from utils.state import set_state, get_state, clear_state
from config import D360_API_KEY, D360_BASE_URL

# ============================================================================
# НАСТРОЙКИ ТЕСТА
# ============================================================================

# Замените на реальный номер телефона в формате: 79991234567
TEST_PHONE = "79991234567"

# ============================================================================
# ЦВЕТА ДЛЯ ТЕРМИНАЛА
# ============================================================================

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(text):
    print(f"{Colors.GREEN}✓{Colors.RESET} {text}")

def print_error(text):
    print(f"{Colors.RED}✗{Colors.RESET} {text}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {text}")

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{text}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{'='*60}{Colors.RESET}\n")

# ============================================================================
# ТЕСТЫ
# ============================================================================

def test_config():
    """Тест 1: Проверка конфигурации"""
    print_header("ТЕСТ 1: Проверка конфигурации")
    
    try:
        from config import get_headers
        headers = get_headers()
        
        assert "Content-Type" in headers, "Отсутствует Content-Type"
        assert "D360-API-KEY" in headers, "Отсутствует D360-API-KEY"
        assert headers["Content-Type"] == "application/json", "Неверный Content-Type"
        
        print_success(f"D360_BASE_URL: {D360_BASE_URL}")
        print_success(f"D360_API_KEY: {D360_API_KEY[:10]}...")
        print_success(f"Headers: {headers}")
        print_success("Конфигурация загружена успешно")
        return True
    except Exception as e:
        print_error(f"Ошибка конфигурации: {e}")
        return False


def test_state_management():
    """Тест 2: Проверка управления состоянием"""
    print_header("ТЕСТ 2: Управление состоянием")
    
    try:
        test_user = "test_user_123"
        
        # Тест set_state
        set_state(test_user, "waiting_hours")
        state = get_state(test_user)
        assert state["state"] == "waiting_hours", "Состояние не установлено"
        print_success(f"set_state(): {state}")
        
        # Тест get_state
        current_state = state.get("state")
        assert current_state == "waiting_hours", "Состояние не получено"
        print_success(f"get_state(): {current_state}")
        
        # Тест set_state с данными
        set_state(test_user, "shift_selected", {"shift": "1", "hours": 8})
        state = get_state(test_user)
        assert state["data"]["shift"] == "1", "Данные не сохранены"
        print_success(f"set_state() с данными: {state}")
        
        # Тест clear_state
        clear_state(test_user)
        state = get_state(test_user)
        assert state["state"] is None, "Состояние не очищено"
        print_success(f"clear_state(): {state}")
        
        print_success("Управление состоянием работает корректно")
        return True
    except Exception as e:
        print_error(f"Ошибка управления состоянием: {e}")
        return False


def test_send_text_message():
    """Тест 3: Отправка текстового сообщения"""
    print_header("ТЕСТ 3: Отправка текстового сообщения")
    
    try:
        data = {
            "type": "text",
            "text": {
                "body": "🤖 Тестовое сообщение от бота!\n\nЭто проверка работы 360dialog API."
            }
        }
        
        print_info(f"Отправка на номер: {TEST_PHONE}")
        print_info(f"Данные: {data}")
        
        result = send_message(TEST_PHONE, data)
        
        if result:
            print_success("Текстовое сообщение отправлено успешно!")
            print_info("Проверьте WhatsApp")
            return True
        else:
            print_error("Не удалось отправить текстовое сообщение")
            return False
    except Exception as e:
        print_error(f"Ошибка отправки текстового сообщения: {e}")
        return False


def test_send_buttons():
    """Тест 4: Отправка интерактивных кнопок"""
    print_header("ТЕСТ 4: Отправка интерактивных кнопок")
    
    try:
        text = "🎯 Тест интерактивных кнопок!\n\nВыберите одну из кнопок ниже:"
        buttons = [
            {"id": "test_btn_1", "title": "Кнопка 1"},
            {"id": "test_btn_2", "title": "Кнопка 2"},
            {"id": "test_btn_3", "title": "Кнопка 3"}
        ]
        
        print_info(f"Отправка на номер: {TEST_PHONE}")
        print_info(f"Текст: {text}")
        print_info(f"Кнопки: {buttons}")
        
        result = send_buttons(TEST_PHONE, text, buttons)
        
        if result:
            print_success("Интерактивные кнопки отправлены успешно!")
            print_info("Проверьте WhatsApp и нажмите на кнопку")
            return True
        else:
            print_error("Не удалось отправить кнопки")
            return False
    except Exception as e:
        print_error(f"Ошибка отправки кнопок: {e}")
        return False


def test_send_list():
    """Тест 5: Отправка списка"""
    print_header("ТЕСТ 5: Отправка списка (list message)")
    
    try:
        text = "📋 Тест списка!\n\nНажмите кнопку ниже, чтобы открыть список опций."
        button_text = "Открыть список"
        sections = [
            {
                "title": "Тестовые опции",
                "rows": [
                    {
                        "id": "test_list_1",
                        "title": "Опция 1",
                        "description": "Описание первой опции"
                    },
                    {
                        "id": "test_list_2",
                        "title": "Опция 2",
                        "description": "Описание второй опции"
                    },
                    {
                        "id": "test_list_3",
                        "title": "Опция 3",
                        "description": "Описание третьей опции"
                    }
                ]
            }
        ]
        
        print_info(f"Отправка на номер: {TEST_PHONE}")
        print_info(f"Текст: {text}")
        print_info(f"Секции: {len(sections)}, Строк: {len(sections[0]['rows'])}")
        
        result = send_list(TEST_PHONE, text, button_text, sections)
        
        if result:
            print_success("Список отправлен успешно!")
            print_info("Проверьте WhatsApp и выберите опцию из списка")
            return True
        else:
            print_error("Не удалось отправить список")
            return False
    except Exception as e:
        print_error(f"Ошибка отправки списка: {e}")
        return False


def test_main_menu():
    """Тест 6: Главное меню бота"""
    print_header("ТЕСТ 6: Главное меню бота")
    
    try:
        from menu_handlers import handle_main_menu
        
        print_info(f"Отправка главного меню на: {TEST_PHONE}")
        handle_main_menu(TEST_PHONE)
        
        print_success("Главное меню отправлено!")
        print_info("Проверьте WhatsApp - должны появиться кнопки: Работа, Часы, Помощь")
        return True
    except Exception as e:
        print_error(f"Ошибка отправки главного меню: {e}")
        return False


def test_shift_menu():
    """Тест 7: Меню смен"""
    print_header("ТЕСТ 7: Меню смен")
    
    try:
        from menu_handlers import handle_shift_menu
        
        print_info(f"Отправка меню смен на: {TEST_PHONE}")
        handle_shift_menu(TEST_PHONE)
        
        print_success("Меню смен отправлено!")
        print_info("Проверьте WhatsApp - должен появиться список с 3 сменами")
        return True
    except Exception as e:
        print_error(f"Ошибка отправки меню смен: {e}")
        return False


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    """Запуск всех тестов"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}╔══════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}║     Тестирование 360dialog Cloud API Integration        ║{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}╚══════════════════════════════════════════════════════════╝{Colors.RESET}\n")
    
    # Проверка номера телефона
    if TEST_PHONE == "79991234567":
        print_error("ВНИМАНИЕ: Не забудьте заменить TEST_PHONE на реальный номер!")
        print_info(f"Откройте {__file__} и измените TEST_PHONE")
        response = input("\nПродолжить с тестовым номером? (y/n): ")
        if response.lower() != 'y':
            print_info("Тестирование отменено")
            sys.exit(0)
    
    # Список тестов
    tests = [
        ("Конфигурация", test_config, True),
        ("Управление состоянием", test_state_management, True),
        ("Текстовое сообщение", test_send_text_message, False),
        ("Интерактивные кнопки", test_send_buttons, False),
        ("Список (list)", test_send_list, False),
        ("Главное меню", test_main_menu, False),
        ("Меню смен", test_shift_menu, False),
    ]
    
    results = []
    
    # Запуск тестов
    for test_name, test_func, is_required in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            
            if not is_required and result:
                # Пауза между отправкой сообщений (чтобы не перегрузить API)
                print_info("Пауза 2 сек...")
                time.sleep(2)
        except Exception as e:
            print_error(f"Критическая ошибка в тесте '{test_name}': {e}")
            results.append((test_name, False))
    
    # Итоги
    print_header("РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{Colors.GREEN}PASSED{Colors.RESET}" if result else f"{Colors.RED}FAILED{Colors.RESET}"
        print(f"  {status}  {test_name}")
    
    print(f"\n{Colors.BOLD}Итого: {passed}/{total} тестов пройдено{Colors.RESET}\n")
    
    if passed == total:
        print_success("Все тесты пройдены успешно! 🎉")
        print_info("Проект готов к работе с 360dialog Cloud API")
    else:
        print_error(f"Некоторые тесты не прошли ({total - passed} ошибок)")
        print_info("Проверьте логи выше для деталей")
    
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_info("\n\nТестирование прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print_error(f"\n\nКритическая ошибка: {e}")
        sys.exit(1)

