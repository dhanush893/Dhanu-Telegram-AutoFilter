FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Koyeb Web Service requires a listening HTTP/TCP port.
# Run the Telegram worker and the health server together.
CMD ["sh", "-c", "python health_server.py & exec python main.py"]
