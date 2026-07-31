# Railway builds from the repository root, so this image copies the backend and
# the workbooks it seeds from. backend/Dockerfile is kept for docker-compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/alembic.ini .
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/discovery_engine ./discovery_engine
COPY backend/gateway.py backend/bootstrap.py backend/release.py ./
COPY backend/discovery_engine_seed.db ./discovery_engine_seed.db

# Source workbooks the deployment seeds itself from.
COPY backend/misseddata ./misseddata
COPY backend/other_cities ./other_cities

# The signed-off Denpasar customer pack is served for download.
COPY sample_output ./sample_output

RUN mkdir -p /app/data /app/evidence_storage_customer

# Railway supplies PORT; the default keeps `docker run` working locally.
ENV PORT=8000
EXPOSE 8000

CMD ["python", "release.py"]
