# ---- build stage ----
FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime ----
COPY . .
# Puerto que Render inyecta
ENV PORT=8000
CMD gunicorn app:app --bind 0.0.0.0:$PORT