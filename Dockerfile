FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Import health_server first so its Telethon numeric-ID resolver is active in main.
CMD ["python", "-c", "import health_server; import main; import asyncio; asyncio.run(main.main())"]
