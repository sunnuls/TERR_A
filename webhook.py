# webhook.py
"""
Обработка webhook запросов от 360dialog.
Поддержка FSM (машины состояний).
"""
import logging
from flask import Blueprint, request, jsonify
from config import VERIFY_TOKEN
from menu_handlers import handle_incoming_message
from utils.state import get_state, States

logger = logging.getLogger(__name__)

# Создаём Blueprint для webhook
webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('/webhook', methods=['GET'])
def webhook_verify():
    """
    GET /webhook - верификация webhook от 360dialog.
    
    360dialog отправляет запрос с параметрами:
    - hub.mode = "subscribe"
    - hub.verify_token = токен для проверки
    - hub.challenge = строка для ответа
    """
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    logger.info(f"📥 Получен запрос верификации webhook: mode={mode}, token={'***' if token else None}")
    
    # Проверяем токен
    if mode == 'subscribe' and token == VERIFY_TOKEN:
        logger.info("✅ Webhook верифицирован успешно")
        return challenge, 200
    else:
        logger.warning("❌ Ошибка верификации webhook: неверный токен")
        return 'Forbidden', 403


@webhook_bp.route('/webhook', methods=['POST'])
def webhook_receive():
    """
    POST /webhook - приём входящих сообщений от 360dialog.
    
    Структура данных от 360dialog:
    {
        "messages": [{
            "from": "79991234567",
            "id": "message_id",
            "timestamp": "1234567890",
            "type": "text" | "interactive",
            "text": {"body": "Hello"},
            "interactive": {
                "type": "button_reply" | "list_reply",
                "button_reply": {"id": "btn_id", "title": "Button"},
                "list_reply": {"id": "row_id", "title": "Row", "description": "..."}
            }
        }]
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            logger.warning("[WARN] Получен пустой webhook запрос")
            return jsonify({"status": "error", "message": "No data"}), 400
        
        logger.info(f"[WEBHOOK] Получен webhook: {data}")
        
        # Обработка сообщений
        # 360dialog присылает данные в формате: entry[0].changes[0].value.messages
        messages = []
        
        if 'entry' in data:
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    messages.extend(value.get('messages', []))
        
        # Фоллбэк для прямого формата (если вдруг)
        if not messages:
            messages = data.get('messages', [])
        
        for message in messages:
            try:
                phone = message.get('from')
                msg_type = message.get('type')
                
                # Получаем текущее состояние FSM пользователя
                user_state = get_state(phone)
                current_state = user_state.get('state')
                
                logger.info(f"[MSG] От {phone}, тип: {msg_type}, состояние FSM: {current_state}")
                
                if msg_type == 'text':
                    # Текстовое сообщение
                    text_body = message.get('text', {}).get('body', '').strip()
                    logger.info(f"[TEXT] {phone}: {text_body}")
                    
                    # FSM: Обработка в зависимости от состояния
                    if current_state == States.SELECT_WORK:
                        logger.info(f"[FSM] Состояние SELECT_WORK - обработка текста")
                    elif current_state == States.SELECT_SHIFT:
                        logger.info(f"[FSM] Состояние SELECT_SHIFT - обработка текста")
                    elif current_state == States.SELECT_HOURS:
                        logger.info(f"[FSM] Состояние SELECT_HOURS - обработка текста")
                    elif current_state == States.CONFIRM_SAVE:
                        logger.info(f"[FSM] Состояние CONFIRM_SAVE - обработка текста")
                    
                    handle_incoming_message(message)
                
                elif msg_type == 'interactive':
                    # Интерактивное сообщение (кнопка или список)
                    interactive = message.get('interactive', {})
                    interactive_type = interactive.get('type')
                    
                    if interactive_type == 'button_reply':
                        # Ответ на кнопку
                        button_reply = interactive.get('button_reply', {})
                        button_id = button_reply.get('id', '')
                        button_title = button_reply.get('title', '')
                        logger.info(f"[BUTTON] {phone}: {button_id} ({button_title})")
                        
                        # FSM: Обработка кнопок в зависимости от состояния
                        if current_state == States.CONFIRM_SAVE:
                            logger.info(f"[FSM] Состояние CONFIRM_SAVE - обработка кнопки подтверждения")
                        
                        # Добавляем button_id в message для обработки
                        message['button_id'] = button_id
                        handle_incoming_message(message)
                    
                    elif interactive_type == 'list_reply':
                        # Ответ на список
                        list_reply = interactive.get('list_reply', {})
                        list_id = list_reply.get('id', '')
                        list_title = list_reply.get('title', '')
                        logger.info(f"[LIST] {phone}: {list_id} ({list_title})")
                        
                        # FSM: Обработка списков в зависимости от состояния
                        if current_state == States.SELECT_WORK:
                            logger.info(f"[FSM] Состояние SELECT_WORK - обработка выбора работы")
                        elif current_state == States.SELECT_SHIFT:
                            logger.info(f"[FSM] Состояние SELECT_SHIFT - обработка выбора смены")
                        elif current_state == States.SELECT_HOURS:
                            logger.info(f"[FSM] Состояние SELECT_HOURS - обработка выбора часов")
                        
                        # Добавляем list_id в message для обработки
                        message['list_id'] = list_id
                        handle_incoming_message(message)
                
                else:
                    logger.warning(f"[WARN] Неподдерживаемый тип сообщения: {msg_type}")
                    
            except Exception as e:
                logger.error(f"[ERROR] Ошибка обработки сообщения: {e}", exc_info=True)
        
        # Обработка статусов доставки (опционально)
        statuses = data.get('statuses', [])
        if statuses:
            logger.debug(f"[STATUS] Получены статусы: {statuses}")
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"[ERROR] Ошибка в webhook_receive: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@webhook_bp.route('/health', methods=['GET'])
def health_check():
    """
    GET /health - проверка работоспособности сервера.
    """
    return jsonify({
        "status": "healthy",
        "service": "WhatsApp Bot 360dialog"
    }), 200

