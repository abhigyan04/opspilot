FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/opspilot

COPY pyproject.toml ./
COPY app/ ./app/
COPY data/scenarios/ ./data/scenarios/

RUN python -m pip install . \
    && python -m pip check \
    && groupadd --gid 10001 opspilot \
    && useradd --uid 10001 --gid opspilot --create-home opspilot \
    && mkdir -p out/workflows \
    && chown -R opspilot:opspilot out

USER opspilot

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
