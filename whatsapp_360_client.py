# whatsapp_360_client.py
# Wrapper для 360dialog WhatsApp API

import requests
import logging
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass


@dataclass
class Button:
    """Кнопка для интерактивных сообщений"""
    title: str
    callback_data: str


class WhatsApp360Client:
    """Клиент для работы с 360dialog WhatsApp API"""
    
    def __init__(self, api_key: str, base_url: str = "https://waba-v2.360dialog.io"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "D360-API-KEY": api_key,
            "Content-Type": "application/json"
        })
        
        # Хранилище обработчиков
        self.message_handlers = []
        self.callback_handlers = []
    
    def send_message(self, to: str, text: str, buttons: Optional[List[Button]] = None) -> Dict:
        """
        Отправка сообщения (текст или с кнопками)
        
        Args:
            to: Номер получателя (например "79898341458")
            text: Текст сообщения
            buttons: Список кнопок (максимум 3)
        
        Returns:
            Response от API
        """
        url = f"{self.base_url}/messages"
        
        # Базовая структура сообщения
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text" if not buttons else "interactive"
        }
        
        if buttons:
            # Интерактивное сообщение с кнопками
            payload["type"] = "interactive"
            payload["interactive"] = {
                "type": "button",
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": btn.callback_data,
                                "title": btn.title[:20]  # Максимум 20 символов
                            }
                        }
                        for btn in buttons[:3]  # Максимум 3 кнопки
                    ]
                }
            }
        else:
            # Простое текстовое сообщение
            payload["text"] = {
                "body": text
            }
        
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            logging.info(f"✅ Message sent to {to}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Failed to send message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response: {e.response.text}")
            raise

    def send_list_message(self, to: str, body_text: str, button_text: str, sections: List[Dict], header_text: Optional[str] = None) -> Dict:
        """
        Отправка сообщения со списком (List Message)
        
        Args:
            to: Номер получателя
            body_text: Текст сообщения
            button_text: Текст на кнопке открытия списка
            sections: Список секций. Каждая секция: {"title": "...", "rows": [{"id": "...", "title": "...", "description": "..."}]}
            header_text: Заголовок (опционально)
        """
        url = f"{self.base_url}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {
                    "text": body_text
                },
                "action": {
                    "button": button_text,
                    "sections": sections
                }
            }
        }
        
        if header_text:
            payload["interactive"]["header"] = {
                "type": "text",
                "text": header_text
            }
            
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            logging.info(f"✅ List message sent to {to}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Failed to send list message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response: {e.response.text}")
            raise
    
    def send_message_with_cta(self, to: str, text: str, url: str, button_text: str = "Open Link") -> Dict:
        """
        Отправка сообщения с CTA кнопкой (Call-to-Action)
        
        Args:
            to: Номер получателя
            text: Текст сообщения
            url: URL для открытия
            button_text: Текст на кнопке (по умолчанию "Open Link")
        """
        url_endpoint = f"{self.base_url}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {
                    "text": text
                },
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": button_text[:20],
                        "url": url
                    }
                }
            }
        }
        
        try:
            response = self.session.post(url_endpoint, json=payload)
            response.raise_for_status()
            logging.info(f"✅ CTA message sent to {to}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Failed to send CTA message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response: {e.response.text}")
            raise
    
    def send_text_with_quick_replies(self, to: str, text: str, quick_replies: List[Dict[str, str]]) -> Dict:
        """
        Отправка текстового сообщения с Quick Reply кнопками
        
        Args:
            to: Номер получателя
            text: Текст сообщения
            quick_replies: Список кнопок [{"id": "callback_data", "title": "Button Text"}]
                          Максимум 13 кнопок, title до 20 символов
        """
        url = f"{self.base_url}/messages"
        
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": text
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": btn["id"],
                                "title": btn["title"][:20]
                            }
                        }
                        for btn in quick_replies[:3]  # WhatsApp limits to 3 reply buttons
                    ]
                }
            }
        }
        
        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            logging.info(f"✅ Quick reply message sent to {to}")
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Failed to send quick reply message: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logging.error(f"Response: {e.response.text}")
            raise
    
    
    
    def on_message(self, func: Callable):
        """Декоратор для регистрации обработчика текстовых сообщений"""
        self.message_handlers.append(func)
        return func
    
    def on_callback_button(self, func: Callable):
        """Декоратор для регистрации обработчика нажатий на кнопки"""
        self.callback_handlers.append(func)
        return func
    
    def process_webhook(self, webhook_data: Dict):
        """
        Обработка входящего webhook от 360dialog
        
        Args:
            webhook_data: JSON данные от webhook
        """
        try:
            # Структура webhook от 360dialog
            if "entry" not in webhook_data:
                return
            
            for entry in webhook_data.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    
                    # Обработка входящих сообщений
                    for message in value.get("messages", []):
                        self._handle_message(message, value.get("contacts", []))
                    
                    # Обработка статусов (опционально)
                    for status in value.get("statuses", []):
                        logging.info(f"Message status: {status.get('status')}")
        
        except Exception as e:
            logging.error(f"Error processing webhook: {e}")
    
    def _handle_message(self, message: Dict, contacts: List[Dict]):
        """Внутренний метод обработки сообщения"""
        msg_type = message.get("type")
        from_number = message.get("from")
        
        # Получаем имя контакта
        contact_name = None
        for contact in contacts:
            if contact.get("wa_id") == from_number:
                contact_name = contact.get("profile", {}).get("name")
                break
        
        # Создаём объект сообщения
        msg_obj = MessageObject(
            from_user=UserObject(wa_id=from_number, name=contact_name),
            message_id=message.get("id"),
            timestamp=message.get("timestamp"),
            type=msg_type
        )
        
        if msg_type == "text":
            # Текстовое сообщение
            msg_obj.text = message.get("text", {}).get("body", "")
            for handler in self.message_handlers:
                try:
                    handler(self, msg_obj)
                except Exception as e:
                    logging.error(f"Error in message handler: {e}")
        
        elif msg_type == "interactive":
            # Нажатие на кнопку или выбор из списка
            interactive = message.get("interactive", {})
            interactive_type = interactive.get("type")
            
            if interactive_type == "button_reply":
                button_reply = interactive.get("button_reply", {})
                callback_obj = CallbackObject(
                    from_user=msg_obj.from_user,
                    data=button_reply.get("id", ""),
                    title=button_reply.get("title", "")
                )
                for handler in self.callback_handlers:
                    try:
                        handler(self, callback_obj)
                    except Exception as e:
                        logging.error(f"Error in callback handler: {e}")
            
            elif interactive_type == "list_reply":
                list_reply = interactive.get("list_reply", {})
                callback_obj = CallbackObject(
                    from_user=msg_obj.from_user,
                    data=list_reply.get("id", ""),
                    title=list_reply.get("title", "")
                )
                for handler in self.callback_handlers:
                    try:
                        handler(self, callback_obj)
                    except Exception as e:
                        logging.error(f"Error in callback handler: {e}")


@dataclass
class UserObject:
    """Объект пользователя"""
    wa_id: str
    name: Optional[str] = None


@dataclass
class MessageObject:
    """Объект входящего сообщения"""
    from_user: UserObject
    message_id: str
    timestamp: str
    type: str
    text: str = ""


@dataclass
class CallbackObject:
    """Объект callback от кнопки"""
    from_user: UserObject
    data: str
    title: str
