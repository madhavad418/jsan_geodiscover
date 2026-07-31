FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY discovery_engine ./discovery_engine
COPY discovery_engine_seed.db ./discovery_engine_seed.db
COPY gateway.py bootstrap.py ./
RUN mkdir -p /app/data /app/evidence_storage_customer

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python bootstrap.py && uvicorn gateway:app --host 0.0.0.0 --port 8000"]
