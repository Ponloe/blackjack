FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BLACKJACK_DB=/var/lib/blackjack/session.sqlite3

WORKDIR /app
COPY requirements.txt /app/
RUN sed '/^opencv-python[>=<]/d' requirements.txt > /tmp/requirements-container.txt \
    && pip install --no-cache-dir -r /tmp/requirements-container.txt 'opencv-python-headless>=4.10,<5' \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /var/lib/blackjack \
    && chown appuser:appuser /var/lib/blackjack

COPY --chown=appuser:appuser app /app/app
COPY --chown=appuser:appuser core /app/core
COPY --chown=appuser:appuser vision /app/vision
COPY --chown=appuser:appuser web /app/web
COPY --chown=appuser:appuser data/basic_strategy.json /app/data/basic_strategy.json
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
