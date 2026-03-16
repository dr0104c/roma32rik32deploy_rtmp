FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

EXPOSE 8000

CMD ["/bin/sh", "-ec", "LOG_LEVEL_NORMALIZED=$(printf '%s' \"${LOG_LEVEL:-info}\" | tr '[:upper:]' '[:lower:]'); exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level \"$LOG_LEVEL_NORMALIZED\" $( [ \"${ACCESS_LOG_ENABLED:-true}\" = \"true\" ] && printf %s '--access-log' || printf %s '--no-access-log' )"]
