FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bind the health port before importing main so platform health checks do not
# fail when application configuration is invalid or incomplete.
CMD ["python", "-u", "entrypoint.py"]
