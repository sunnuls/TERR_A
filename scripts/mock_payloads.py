# scripts/mock_payloads.py
"""
Эмуляция входящих сообщений от 360dialog для тестирования бота.
Содержит примеры payload'ов и функции для их отправки.
"""

import requests
import json

# URL вашего локального сервера
WEBHOOK_URL = "http://localhost:8000/webhook"


def send_text_message(phone: str = "79991234567", text: str = "меню"):
    """
    Эмулирует входящее текстовое сообщение.
    
    Args:
        phone: Номер телефона отправителя
        text: Текст сообщения
    """
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.test123",
                                    "timestamp": "1699999999",
                                    "type": "text",
                                    "text": {
                                        "body": text
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    
    print(f"📤 Отправка текста: '{text}' от {phone}")
    print(f"📋 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        print(f"✅ Ответ: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def send_button_click(phone: str = "79991234567", button_id: str = "FILL_TODAY", button_title: str = "Заполнить за сегодня"):
    """
    Эмулирует нажатие на интерактивную кнопку (button_reply).
    
    Args:
        phone: Номер телефона отправителя
        button_id: ID кнопки (например: FILL_TODAY)
        button_title: Название кнопки
    """
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.test456",
                                    "timestamp": "1699999999",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {
                                            "id": button_id,
                                            "title": button_title
                                        }
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    
    print(f"📤 Отправка клика на кнопку: '{button_id}' от {phone}")
    print(f"📋 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        print(f"✅ Ответ: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def send_list_selection(phone: str = "79991234567", list_id: str = "SHIFT_DAY", list_title: str = "Дневная (08:00–20:00)"):
    """
    Эмулирует выбор элемента из интерактивного списка (list_reply).
    
    Args:
        phone: Номер телефона отправителя
        list_id: ID элемента списка (например: SHIFT_DAY)
        list_title: Название элемента
    """
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": phone,
                                    "id": "wamid.test789",
                                    "timestamp": "1699999999",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "list_reply",
                                        "list_reply": {
                                            "id": list_id,
                                            "title": list_title
                                        }
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    
    print(f"📤 Отправка выбора из списка: '{list_id}' от {phone}")
    print(f"📋 Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        print(f"✅ Ответ: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")


def run_full_scenario():
    """
    Запускает полный сценарий тестирования:
    1. Отправка текста "меню"
    2. Нажатие кнопки "Заполнить за сегодня"
    3. Выбор смены из списка
    """
    print("\n" + "="*60)
    print("🚀 ЗАПУСК ПОЛНОГО СЦЕНАРИЯ ТЕСТИРОВАНИЯ")
    print("="*60 + "\n")
    
    phone = "79991234567"
    
    # Шаг 1: Текстовое сообщение "меню"
    print("\n--- ШАГ 1: Отправка текста 'меню' ---")
    send_text_message(phone, "меню")
    input("\n⏸️  Нажмите Enter для продолжения...")
    
    # Шаг 2: Нажатие кнопки "Заполнить за сегодня"
    print("\n--- ШАГ 2: Нажатие кнопки 'Заполнить за сегодня' ---")
    send_button_click(phone, "FILL_TODAY", "Заполнить за сегодня")
    input("\n⏸️  Нажмите Enter для продолжения...")
    
    # Шаг 3: Выбор дневной смены
    print("\n--- ШАГ 3: Выбор дневной смены ---")
    send_list_selection(phone, "SHIFT_DAY", "Дневная (08:00–20:00)")
    
    print("\n" + "="*60)
    print("✅ СЦЕНАРИЙ ЗАВЕРШЁН")
    print("="*60 + "\n")


# ============================================================================
# Инструкции по использованию через curl (для ручного тестирования)
# ============================================================================

CURL_EXAMPLES = """
================================================================================
ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ ЧЕРЕЗ CURL (для ручного тестирования)
================================================================================

1. Текстовое сообщение "меню":
   
   curl -X POST http://localhost:8000/webhook \\
     -H "Content-Type: application/json" \\
     -d '{
       "entry": [{
         "changes": [{
           "value": {
             "messages": [{
               "from": "79991234567",
               "type": "text",
               "text": {"body": "меню"}
             }]
           }
         }]
       }]
     }'

2. Нажатие кнопки "Заполнить за сегодня":
   
   curl -X POST http://localhost:8000/webhook \\
     -H "Content-Type: application/json" \\
     -d '{
       "entry": [{
         "changes": [{
           "value": {
             "messages": [{
               "from": "79991234567",
               "type": "interactive",
               "interactive": {
                 "type": "button_reply",
                 "button_reply": {
                   "id": "FILL_TODAY",
                   "title": "Заполнить за сегодня"
                 }
               }
             }]
           }
         }]
       }]
     }'

3. Выбор дневной смены:
   
   curl -X POST http://localhost:8000/webhook \\
     -H "Content-Type: application/json" \\
     -d '{
       "entry": [{
         "changes": [{
           "value": {
             "messages": [{
               "from": "79991234567",
               "type": "interactive",
               "interactive": {
                 "type": "list_reply",
                 "list_reply": {
                   "id": "SHIFT_DAY",
                   "title": "Дневная (08:00–20:00)"
                 }
               }
             }]
           }
         }]
       }]
     }'

================================================================================
"""


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "text":
            text = sys.argv[2] if len(sys.argv) > 2 else "меню"
            send_text_message(text=text)
        
        elif command == "button":
            button_id = sys.argv[2] if len(sys.argv) > 2 else "FILL_TODAY"
            send_button_click(button_id=button_id)
        
        elif command == "list":
            list_id = sys.argv[2] if len(sys.argv) > 2 else "SHIFT_DAY"
            send_list_selection(list_id=list_id)
        
        elif command == "full":
            run_full_scenario()
        
        elif command == "curl":
            print(CURL_EXAMPLES)
        
        else:
            print("❌ Неизвестная команда")
            print("\nИспользование:")
            print("  python mock_payloads.py text [текст]")
            print("  python mock_payloads.py button [button_id]")
            print("  python mock_payloads.py list [list_id]")
            print("  python mock_payloads.py full")
            print("  python mock_payloads.py curl")
    else:
        print("\nИспользование:")
        print("  python mock_payloads.py text [текст]       - Отправить текст")
        print("  python mock_payloads.py button [id]        - Нажать кнопку")
        print("  python mock_payloads.py list [id]          - Выбрать из списка")
        print("  python mock_payloads.py full               - Полный сценарий")
        print("  python mock_payloads.py curl               - Показать примеры curl")
        print("\nПо умолчанию запускаем полный сценарий...\n")
        run_full_scenario()

