# Browsers + deps already installed here
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python deps (no playwright install here—already baked in)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Collect static assets
RUN python manage.py collectstatic --noinput

EXPOSE 8080
# Run migrations then start gunicorn
CMD ["sh","-c","python manage.py migrate && gunicorn -b 0.0.0.0:8080 --access-logfile - --error-logfile - bonk_skin_search.wsgi:application"]
