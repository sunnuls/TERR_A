FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов проекта
COPY . .

# Создание директории для данных
RUN mkdir -p /app/data

# Переменные окружения по умолчанию
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8000
ENV TZ=Europe/Moscow

# Открытие порта
EXPOSE 8000

# Запуск бота
CMD ["python", "bot.py"]
