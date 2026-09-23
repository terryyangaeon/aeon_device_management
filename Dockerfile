FROM python:3.11-slim

WORKDIR /app

# Install deps first for cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080

# Use gunicorn for prod (Flask dev server is single-threaded)
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60 app:app
