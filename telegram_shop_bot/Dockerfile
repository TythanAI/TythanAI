# Docker-образ для бота-магазина.
#
# Сборка:  docker build -t shop-bot .
# Запуск:  docker run -d --name shop-bot --restart=always \
#            --env-file .env -v "$PWD/data:/app/data" shop-bot
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# База данных хранится здесь — монтируй том, чтобы данные не терялись.
VOLUME ["/app/data"]

CMD ["python", "run.py"]
