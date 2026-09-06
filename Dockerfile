# Клиент-песочница для примеров, которым нужен настоящий
# кластерный клиент внутри docker-сети.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY app/ /app/
COPY scripts/ /scripts/

CMD ["sleep", "infinity"]
