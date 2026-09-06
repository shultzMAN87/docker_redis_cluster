# Базовый образ Python
FROM python:3.10-slim

# Установка рабочей директории
WORKDIR /app

# Установим системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

# Установим pip и необходимые библиотеки
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY /app .

# Создание точки входа
CMD ["sleep", "infinity"]