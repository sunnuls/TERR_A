#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки FSM (машины состояний).

Использование:
    python test_fsm.py
"""
import sys
import io

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from utils.state import (
    get_state, set_state, clear_state,
    update_user_data, get_user_data,
    States
)

# Цвета для терминала
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(text):
    print(f"{Colors.GREEN}✓{Colors.RESET} {text}")

def print_error(text):
    print(f"{Colors.RED}✗{Colors.RESET} {text}")

def print_info(text):
    print(f"{Colors.BLUE}ℹ{Colors.RESET} {text}")

def print_state(text):
    print(f"{Colors.MAGENTA}▸{Colors.RESET} {text}")

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.YELLOW}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{text:^70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.YELLOW}{'='*70}{Colors.RESET}\n")

def print_subheader(text):
    print(f"\n{Colors.CYAN}{text}{Colors.RESET}")
    print(f"{Colors.CYAN}{'-'*70}{Colors.RESET}")


# ============================================================================
# ТЕСТЫ FSM
# ============================================================================

def test_states_constants():
    """Тест 1: Проверка констант состояний"""
    print_header("ТЕСТ 1: Константы состояний FSM")
    
    try:
        assert hasattr(States, 'MAIN_MENU'), "Отсутствует States.MAIN_MENU"
        assert hasattr(States, 'SELECT_WORK'), "Отсутствует States.SELECT_WORK"
        assert hasattr(States, 'SELECT_SHIFT'), "Отсутствует States.SELECT_SHIFT"
        assert hasattr(States, 'SELECT_HOURS'), "Отсутствует States.SELECT_HOURS"
        assert hasattr(States, 'CONFIRM_SAVE'), "Отсутствует States.CONFIRM_SAVE"
        
        print_info(f"States.MAIN_MENU     = '{States.MAIN_MENU}'")
        print_info(f"States.SELECT_WORK   = '{States.SELECT_WORK}'")
        print_info(f"States.SELECT_SHIFT  = '{States.SELECT_SHIFT}'")
        print_info(f"States.SELECT_HOURS  = '{States.SELECT_HOURS}'")
        print_info(f"States.CONFIRM_SAVE  = '{States.CONFIRM_SAVE}'")
        
        print_success("Все константы состояний определены")
        return True
    except Exception as e:
        print_error(f"Ошибка: {e}")
        return False


def test_state_management():
    """Тест 2: Управление состоянием"""
    print_header("ТЕСТ 2: Управление состоянием")
    
    test_phone = "test_79991234567"
    
    try:
        # Тест 2.1: Установка состояния
        print_subheader("2.1. Установка состояния")
        set_state(test_phone, States.MAIN_MENU)
        state = get_state(test_phone)
        assert state['state'] == States.MAIN_MENU, "Состояние не установлено"
        print_state(f"set_state('{test_phone}', States.MAIN_MENU)")
        print_info(f"Результат: {state}")
        print_success("Состояние установлено корректно")
        
        # Тест 2.2: Получение состояния
        print_subheader("2.2. Получение состояния")
        current_state = state.get('state')
        assert current_state == States.MAIN_MENU, "Ошибка получения состояния"
        print_state(f"get_state('{test_phone}')")
        print_info(f"Текущее состояние: {current_state}")
        print_success("Состояние получено корректно")
        
        # Тест 2.3: Очистка состояния
        print_subheader("2.3. Очистка состояния")
        clear_state(test_phone)
        state = get_state(test_phone)
        assert state['state'] is None, "Состояние не очищено"
        print_state(f"clear_state('{test_phone}')")
        print_info(f"Результат: {state}")
        print_success("Состояние очищено корректно")
        
        return True
    except Exception as e:
        print_error(f"Ошибка: {e}")
        return False


def test_state_data():
    """Тест 3: Работа с данными состояния"""
    print_header("ТЕСТ 3: Работа с данными состояния")
    
    test_phone = "test_79997654321"
    
    try:
        # Тест 3.1: Сохранение данных
        print_subheader("3.1. Сохранение данных")
        set_state(test_phone, States.SELECT_WORK)
        update_user_data(test_phone, 'work', 'Поле')
        update_user_data(test_phone, 'work_id', 'work_field')
        
        work = get_user_data(test_phone, 'work')
        work_id = get_user_data(test_phone, 'work_id')
        
        print_state(f"update_user_data('{test_phone}', 'work', 'Поле')")
        print_state(f"update_user_data('{test_phone}', 'work_id', 'work_field')")
        print_info(f"work = {work}")
        print_info(f"work_id = {work_id}")
        
        assert work == 'Поле', "Данные work не сохранены"
        assert work_id == 'work_field', "Данные work_id не сохранены"
        print_success("Данные сохранены корректно")
        
        # Тест 3.2: Получение несуществующих данных с default
        print_subheader("3.2. Получение данных с default значением")
        missing = get_user_data(test_phone, 'missing_key', 'default_value')
        print_state(f"get_user_data('{test_phone}', 'missing_key', 'default_value')")
        print_info(f"Результат: {missing}")
        assert missing == 'default_value', "Default значение не работает"
        print_success("Default значения работают корректно")
        
        # Тест 3.3: Полное состояние
        print_subheader("3.3. Полное состояние с данными")
        state = get_state(test_phone)
        print_state(f"get_state('{test_phone}')")
        print_info(f"Состояние: {state['state']}")
        print_info(f"Данные: {state['data']}")
        assert state['state'] == States.SELECT_WORK, "Состояние не сохранено"
        assert 'work' in state['data'], "Данные не сохранены"
        print_success("Полное состояние с данными работает корректно")
        
        return True
    except Exception as e:
        print_error(f"Ошибка: {e}")
        return False


def test_fsm_flow():
    """Тест 4: Симуляция полного FSM потока"""
    print_header("ТЕСТ 4: Симуляция полного FSM потока")
    
    test_phone = "test_79995556677"
    
    try:
        # Шаг 1: MAIN_MENU
        print_subheader("Шаг 1: MAIN_MENU")
        set_state(test_phone, States.MAIN_MENU)
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_info("Пользователь нажимает 'Работа'")
        print_success("✓ MAIN_MENU")
        
        # Шаг 2: SELECT_WORK
        print_subheader("Шаг 2: SELECT_WORK")
        set_state(test_phone, States.SELECT_WORK)
        print_info("Пользователь выбирает 'Поле'")
        update_user_data(test_phone, 'work', 'Поле')
        update_user_data(test_phone, 'work_id', 'work_field')
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_state(f"Данные: work={state['data'].get('work')}")
        print_success("✓ SELECT_WORK → Работа выбрана")
        
        # Шаг 3: SELECT_SHIFT
        print_subheader("Шаг 3: SELECT_SHIFT")
        set_state(test_phone, States.SELECT_SHIFT)
        print_info("Пользователь выбирает 'Смена 1 (8-16)'")
        update_user_data(test_phone, 'shift', '8-16')
        update_user_data(test_phone, 'shift_id', 'shift_1')
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_state(f"Данные: work={state['data'].get('work')}, shift={state['data'].get('shift')}")
        print_success("✓ SELECT_SHIFT → Смена выбрана")
        
        # Шаг 4: SELECT_HOURS
        print_subheader("Шаг 4: SELECT_HOURS")
        set_state(test_phone, States.SELECT_HOURS)
        print_info("Пользователь выбирает '8 часов'")
        update_user_data(test_phone, 'hours', '8')
        update_user_data(test_phone, 'hours_id', 'hours_8')
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_state(f"Данные: work={state['data'].get('work')}, shift={state['data'].get('shift')}, hours={state['data'].get('hours')}")
        print_success("✓ SELECT_HOURS → Часы выбраны")
        
        # Шаг 5: CONFIRM_SAVE
        print_subheader("Шаг 5: CONFIRM_SAVE")
        set_state(test_phone, States.CONFIRM_SAVE)
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_info("Сводка данных:")
        print_info(f"  ▪ Работа: {state['data'].get('work')}")
        print_info(f"  ▪ Смена: {state['data'].get('shift')}")
        print_info(f"  ▪ Часов: {state['data'].get('hours')}")
        print_info("Пользователь нажимает 'Подтвердить'")
        
        # Проверяем, что все данные на месте
        assert state['data'].get('work') == 'Поле', "Данные work потеряны"
        assert state['data'].get('shift') == '8-16', "Данные shift потеряны"
        assert state['data'].get('hours') == '8', "Данные hours потеряны"
        
        print_success("✓ CONFIRM_SAVE → Данные готовы к сохранению")
        
        # Шаг 6: Сохранение и очистка
        print_subheader("Шаг 6: Сохранение и возврат в MAIN_MENU")
        print_info("Вызов save_entry(phone, 'Поле', '8-16', '8')")
        clear_state(test_phone)
        set_state(test_phone, States.MAIN_MENU)
        state = get_state(test_phone)
        print_state(f"Состояние: {state['state']}")
        print_state(f"Данные: {state['data']}")
        assert state['state'] == States.MAIN_MENU, "Не вернулись в главное меню"
        assert len(state['data']) == 0, "Данные не очищены"
        print_success("✓ Сохранение завершено, состояние сброшено")
        
        return True
    except Exception as e:
        print_error(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_multiple_users():
    """Тест 5: Несколько пользователей одновременно"""
    print_header("ТЕСТ 5: Несколько пользователей одновременно")
    
    users = [
        ("user1_79991111111", States.SELECT_WORK, {"work": "Поле"}),
        ("user2_79992222222", States.SELECT_SHIFT, {"work": "Кабачок", "shift": "8-16"}),
        ("user3_79993333333", States.CONFIRM_SAVE, {"work": "Картошка", "shift": "16-00", "hours": "12"}),
    ]
    
    try:
        # Устанавливаем состояния для всех пользователей
        print_subheader("Установка состояний для 3 пользователей")
        for phone, state, data in users:
            set_state(phone, state)
            for key, value in data.items():
                update_user_data(phone, key, value)
            print_info(f"{phone}: {state} → {data}")
        
        print_success("Состояния установлены для всех пользователей")
        
        # Проверяем, что состояния не смешались
        print_subheader("Проверка изоляции состояний")
        for phone, expected_state, expected_data in users:
            state = get_state(phone)
            actual_state = state['state']
            actual_data = state['data']
            
            print_state(f"{phone}:")
            print_info(f"  Ожидаемое: {expected_state} → {expected_data}")
            print_info(f"  Фактическое: {actual_state} → {actual_data}")
            
            assert actual_state == expected_state, f"Состояние смешалось для {phone}"
            for key, value in expected_data.items():
                assert actual_data.get(key) == value, f"Данные смешались для {phone}"
        
        print_success("Состояния изолированы корректно")
        
        # Очищаем состояния
        print_subheader("Очистка всех состояний")
        for phone, _, _ in users:
            clear_state(phone)
            state = get_state(phone)
            print_info(f"{phone}: {state}")
        
        print_success("Все состояния очищены")
        
        return True
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
    print(f"{Colors.BOLD}{Colors.BLUE}║          Тестирование FSM (Машина состояний)                     ║{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}╚══════════════════════════════════════════════════════════════════╝{Colors.RESET}\n")
    
    # Список тестов
    tests = [
        ("Константы состояний", test_states_constants),
        ("Управление состоянием", test_state_management),
        ("Работа с данными", test_state_data),
        ("Полный FSM поток", test_fsm_flow),
        ("Несколько пользователей", test_multiple_users),
    ]
    
    results = []
    
    # Запуск тестов
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print_error(f"Критическая ошибка в тесте '{test_name}': {e}")
            results.append((test_name, False))
    
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
        print_info("FSM готова к использованию")
    else:
        print_error(f"Некоторые тесты не прошли ({total - passed} ошибок)")
        print_info("Проверьте логи выше для деталей")
        sys.exit(1)
    
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

