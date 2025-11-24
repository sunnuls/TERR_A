import os
import sys
import json
import traceback
import logging

from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests

# Загружаем .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "terra_bot_verify_token_2024")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

if not WHATSAPP_TOKEN:
    print("❌ ERROR: WHATSAPP_TOKEN is not set in .env")
    sys.exit(1)

# v2 API
API_URL = "https://waba-v2.360dialog.io/messages"

HEADERS = {
    "D360-API-KEY": WHATSAPP_TOKEN,
    "Content-Type": "application/json"
}

app = Flask(__name__)


def log_request(label: str, data):
    """Красиво логируем входящие/исходящие данные"""
    print(f"\n=== {label} ===")
    try:
        print(json.dumps(data, indent=4, ensure_ascii=False))
    except Exception:
        print(str(data))
    print("=== END ===\n")


def send_text_message(to: str, text: str):
    """Отправка обычного текстового сообщения через 360dialog v2"""
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "body": text,
            "preview_url": False
        }
    }

    log_request("SEND TEXT PAYLOAD", payload)
    resp = requests.post(API_URL, headers=HEADERS, json=payload)
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    print(f"SEND TEXT RESPONSE: {resp.status_code} {body}")
    return resp


def send_menu_buttons(to: str):
    """Отправка меню с кнопками BTN_START и BTN_MENU"""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "recipient_type": "individual",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Выберите действие:"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "BTN_START",
                            "title": "Старт"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "BTN_MENU",
                            "title": "Меню"
                        }
                    }
                ]
            }
        }
    }

    log_request("SEND MENU PAYLOAD", payload)
    resp = requests.post(API_URL, headers=HEADERS, json=payload)
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    print(f"SEND BUTTONS RESPONSE: {resp.status_code} {body}")
    return resp


def normalize_text(text: str) -> str:
    return (text or "").strip().lower()


@app.route("/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    """Основной обработчик входящих запросов webhook от WhatsApp (360dialog)."""
    if request.method == "GET":
        # Проверка при настройке вебхука (verification challenge)
        hub_mode = request.args.get("hub.mode")
        verify_token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        # Проверяем режим и токен
        if hub_mode == "subscribe" and verify_token == VERIFY_TOKEN:
            logging.info("Webhook verification successful (mode=%s). Sending challenge back.", hub_mode)
            # Возвращаем challenge для подтверждения вебхука
            return challenge, 200
        else:
            logging.warning("Webhook verification failed: invalid token or mode.")
            # Неверный токен – отвечаем 403 Forbidden
            return "Verification token mismatch", 403

    # Обработка POST-запроса (входящее уведомление о сообщении или статусе)
    data = request.get_json(force=True, silent=True)
    if data is None:
        # Если JSON некорректен или отсутствует
        logging.warning("Received an invalid or empty JSON payload in webhook POST.")
        return "EVENT_RECEIVED", 200  # Отвечаем 200, чтобы избежать повторных попыток

    log_request("INCOMING", data)

    # Обходим все записи entry в полученных данных
    entries = data.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            # Извлекаем списки сообщений и статусов, если они есть
            messages = value.get("messages", [])
            statuses = value.get("statuses", [])

            # Обрабатываем все входящие сообщения (если они присутствуют)
            for message in messages:
                try:
                    logging.info(f"Incoming message event: from {message.get('from')} of type {message.get('type')}.")
                    process_incoming_message(message)
                except Exception as e:
                    logging.error(f"Error processing message: {e}", exc_info=True)

            # Обрабатываем все статусы сообщений (если присутствуют)
            for status in statuses:
                try:
                    logging.info(f"Incoming status event: message {status.get('id')} is now {status.get('status')}.")
                    process_message_status(status)
                except Exception as e:
                    logging.error(f"Error processing status: {e}", exc_info=True)

            # Дополнительно можно обработать другие поля в value, например 'errors' или 'contacts', при необходимости.
            # errors = value.get("errors", [])
            # for error in errors:
            #     logging.error(f"Error event in webhook: {error}")

    # Если дошли сюда, значит все вложенные события обработаны.
    # Возвращаем подтверждение получения события WhatsApp, чтобы не было повторных уведомлений.
    return "EVENT_RECEIVED", 200


def process_incoming_message(message: dict) -> None:
    """Обработка входящего сообщения."""
    # Извлекаем базовую информацию о сообщении
    sender = message.get("from")
    msg_type = message.get("type")
    text = None

    if msg_type == "text":
        text = message.get("text", {}).get("body")
        norm = normalize_text(text or "")

        logging.info(f"Processing message from {sender}. Text: {text!r}")

        if norm in ("start", "/start", "старт"):
            send_text_message(sender, "Привет! Это Terra Bot 🌱")
            send_menu_buttons(sender)
        elif norm in ("menu", "меню"):
            send_menu_buttons(sender)
        else:
            # Можно просто ничего не отвечать или отправлять дефолт
            send_text_message(
                sender,
                "Я тебя понял, но пока реагирую только на команды: start / меню."
            )

    elif msg_type == "interactive":
        # Обработка интерактивных сообщений (кнопки)
        interactive = message.get("interactive", {})
        button_id = None

        # Вариант 1: button_reply (Meta / 360dialog)
        if "button_reply" in interactive:
            button_id = interactive["button_reply"].get("id")
        # Вариант 2: button.reply.id
        elif "button" in interactive and "reply" in interactive["button"]:
            button_id = interactive["button"]["reply"].get("id")

        logging.info(f"Processing button from {sender}: {button_id}")

        if button_id == "BTN_START":
            send_text_message(sender, "🚀 Запуск! Бот готов работать.")
            send_menu_buttons(sender)
        elif button_id == "BTN_MENU":
            send_menu_buttons(sender)
    else:
        logging.warning(f"Unsupported message type: {msg_type} from {sender}")

    # TODO: Добавить дополнительную логику обработки входящего сообщения.
    # Например, можно вызвать функцию для ответа пользователю или сохранить сообщение в базу.


def process_message_status(status: dict) -> None:
    """Обработка события статуса сообщения."""
    msg_id = status.get("id")
    status_value = status.get("status")  # например, "sent", "delivered", "read"
    recipient = status.get("recipient_id")

    logging.info(f"Processing status update for message {msg_id}: status = {status_value}, recipient = {recipient}.")

    # TODO: Реализовать нужную обработку статуса (например, отметить сообщение прочитанным в системе).


if __name__ == "__main__":
    print(f"Starting Terra Bot on {SERVER_HOST}:{SERVER_PORT}")
    app.run(host=SERVER_HOST, port=SERVER_PORT)
