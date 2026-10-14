# The Bank Directory API, served by gunicorn. See docs/deploy.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py gunicorn.conf.py ./
COPY src ./src
COPY data ./data

# API keys live in a volume mounted here, so the directory must belong to the app user.
RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /var/lib/bank-directory \
    && chown app /var/lib/bank-directory
USER app

EXPOSE 5006
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5006/', timeout=3)"]
CMD ["gunicorn", "app:app"]
