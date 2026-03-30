FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN mkdir -p /data/monitor /tmp/shermon/logs

ENV MONITOR_DATA_DIR=/data/monitor
ENV MONITOR_DATABASE_URL=sqlite:////data/monitor/monitor.db
ENV MONITOR_LOG_DIR=/tmp/shermon/logs

EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
