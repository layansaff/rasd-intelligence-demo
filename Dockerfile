FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RASD_DATABASE_PATH=/app/data/rasd.sqlite3

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 rasd \
    && useradd --system --uid 10001 --gid rasd --home-dir /app rasd \
    && mkdir -p /app/data \
    && chown -R rasd:rasd /app

COPY --chown=rasd:rasd backend ./backend
COPY --chown=rasd:rasd frontend ./frontend

USER rasd
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
