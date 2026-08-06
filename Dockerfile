# Fedintel — one image, many services. Each Railway service overrides the
# start command (see deploy/railway/*.json). Web is the default CMD.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt
COPY . .
EXPOSE 8000
# Default: web service (migrations run first — idempotent)
CMD ["sh", "-c", "python -m scripts.migrate && uvicorn src.web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
