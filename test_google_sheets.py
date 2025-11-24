#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки Google Sheets интеграции.

Использование:
    python test_google_sheets.py
"""
import sys
import io

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from utils.sheets import init_sheets, save_entry, get_stats, get_sheet_url, is_initialized
from config import SHEETS_ENABLED, SHEET_ID

# Цвета для терминала
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
    print(f"\n{Colors.BOLD}{Colors.YELLOW}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{text:^70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{'='*70}{Colors.RESET}\n")


# ============================================================================
# ТЕСТЫ
# ============================================================================

def test_config():
    """Тест 1: Проверка конфигурации"""
    print_header("ТЕСТ 1: Проверка конфигурации")
    
    try:
        print_info(f"SHEETS_ENABLED: {SHEETS_ENABLED}")
        print_info(f"SHEET_ID: {SHEET_ID if SHEET_ID else '(не указан)'}")
        
        if not SHEETS_ENABLED:
            print_error("Google Sheets интеграция отключена (SHEETS_ENABLED=false)")
            return False
        
        if not SHEET_ID:
            print_error("SHEET_ID не указан в .env")
            return False
        
        print_success("Конфигурация в порядке")
        return True
    except Exception as e:
        print_error(f"Ошибка: {e}")
        return False


def test_initialization():
    """Тест 2: Инициализация Google Sheets"""
    print_header("ТЕСТ 2: Инициализация Google Sheets")
    
    try:
        print_info("Инициализация подключения...")
        success = init_sheets()
        
        if success:
            print_success("Инициализация успешна!")
            
            # Проверка статуса
            if is_initialized():
                print_success("Подключение активно")
            else:
                print_error("Подключение не активно")
                return False
            
            # Получение URL
            url = get_sheet_url()
            if url:
                print_info(f"URL таблицы: {url}")
                print_success("URL таблицы получен")
            else:
                print_error("Не удалось получить URL")
                return False
            
            return True
        else:
            print_error("Инициализация не удалась")
            print_info("Проверьте логи выше для деталей")
            return False
            
    except Exception as e:
        print_error(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_stats():
    """Тест 3: Получение статистики"""
    print_header("ТЕСТ 3: Получение статистики")
    
    if not is_initialized():
        print_error("Google Sheets не инициализированы, пропускаем тест")
        return False
    
    try:
        stats = get_stats()
        
        print_info(f"Статус: {stats.get('status')}")
        
        if stats.get('status') == 'ok':
            print_info(f"Всего записей: {stats.get('total_records')}")
            print_info(f"Название листа: {stats.get('sheet_title')}")
            print_info(f"Название таблицы: {stats.get('spreadsheet_title')}")
            print_info(f"URL: {stats.get('url')}")
            print_success("Статистика получена успешно")
            return True
        else:
            print_error(f"Ошибка получения статистики: {stats.get('message')}")
            return False
            
    except Exception as e:
        print_error(f"Ошибка: {e}")
        return False


def test_save_entry():
    """Тест 4: Сохранение тестовой записи"""
    print_header("ТЕСТ 4: Сохранение тестовой записи")
    
    if not is_initialized():
        print_error("Google Sheets не инициализированы, пропускаем тест")
        return False
    
    try:
        # Тестовые данные
        test_phone = "test_79991234567"
        test_work = "Тестовая работа"
        test_shift = "Тестовая смена"
        test_hours = "8"
        
        print_info("Сохранение тестовой записи...")
        print_info(f"  Телефон: {test_phone}")
        print_info(f"  Работа: {test_work}")
        print_info(f"  Смена: {test_shift}")
        print_info(f"  Часов: {test_hours}")
        
        success = save_entry(test_phone, test_work, test_shift, test_hours)
        
        if success:
            print_success("Тестовая запись сохранена успешно!")
            print_info("Проверьте Google Таблицу - новая строка должна появиться")
            return True
        else:
            print_error("Не удалось сохранить запись")
            return False
            
    except Exception as e:
        print_error(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_save_multiple():
    """Тест 5: Сохранение нескольких записей"""
    print_header("ТЕСТ 5: Сохранение нескольких записей")
    
    if not is_initialized():
        print_error("Google Sheets не инициализированы, пропускаем тест")
        return False
    
    response = input("Сохранить 3 тестовые записи? (y/n): ")
    if response.lower() != 'y':
        print_info("Тест пропущен")
        return True
    
    try:
        test_data = [
            ("test_79991111111", "Поле", "8-16", "8"),
            ("test_79992222222", "Кабачок", "16-00", "6"),
            ("test_79993333333", "Картошка", "00-8", "12"),
        ]
        
        success_count = 0
        
        for i, (phone, work, shift, hours) in enumerate(test_data, 1):
            print_info(f"Запись {i}/3: {work}, {shift}, {hours}ч")
            
            if save_entry(phone, work, shift, hours):
                success_count += 1
                print_success(f"  ✓ Запись {i} сохранена")
            else:
                print_error(f"  ✗ Запись {i} не сохранена")
        
        print_info(f"Сохранено {success_count}/3 записей")
        
        if success_count == 3:
            print_success("Все записи сохранены успешно!")
            return True
        elif success_count > 0:
            print_error(f"Сохранено только {success_count} из 3 записей")
            return False
        else:
            print_error("Не удалось сохранить ни одной записи")
            return False
            
    except Exception as e:
        print_error(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    """Запуск всех тестов"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}╔══════════════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}║       Тестирование Google Sheets интеграции                      ║{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}╚══════════════════════════════════════════════════════════════════╝{Colors.RESET}\n")
    
    # Список тестов
    tests = [
        ("Проверка конфигурации", test_config, True),
        ("Инициализация Google Sheets", test_initialization, True),
        ("Получение статистики", test_get_stats, False),
        ("Сохранение тестовой записи", test_save_entry, False),
        ("Сохранение нескольких записей", test_save_multiple, False),
    ]
    
    results = []
    
    # Запуск тестов
    for test_name, test_func, is_critical in tests:
        try:
            result = test_func()
            results.append((test_name, result))
            
            if is_critical and not result:
                print_error(f"\n❌ Критический тест '{test_name}' не пройден, остальные тесты пропущены")
                break
        except Exception as e:
            print_error(f"Критическая ошибка в тесте '{test_name}': {e}")
            results.append((test_name, False))
            if is_critical:
                break
    
    # Итоги
    print_header("РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = f"{Colors.GREEN}✓ PASSED{Colors.RESET}" if result else f"{Colors.RED}✗ FAILED{Colors.RESET}"
        print(f"  {status}  {test_name}")
    
    print(f"\n{Colors.BOLD}Итого: {passed}/{total} тестов пройдено{Colors.RESET}\n")
    
    if passed == total:
        print_success("Все тесты пройдены успешно! 🎉")
        print_info("Google Sheets интеграция готова к работе")
    else:
        print_error(f"Некоторые тесты не прошли ({total - passed} ошибок)")
        print_info("Проверьте:")
        print_info("  1. SHEETS_ENABLED=true в .env")
        print_info("  2. SHEETS_CREDENTIALS указан правильно")
        print_info("  3. SHEET_ID указан правильно")
        print_info("  4. Service Account имеет доступ к таблице (Share → Editor)")
        print_info("  5. Google Sheets API включен в проекте")
        print_info("\nСм. подробности в GOOGLE_SHEETS_SETUP.md")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_info("\n\nТестирование прервано пользователем")
        sys.exit(0)
    except Exception as e:
        print_error(f"\n\nКритическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

