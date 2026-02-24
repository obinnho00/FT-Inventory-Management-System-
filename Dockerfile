FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# system deps 
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# collectstatic is usually done during deploy, not always in build
# RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "abb_inventory_system.wsgi:application", "--bind", "0.0.0.0:8000"]