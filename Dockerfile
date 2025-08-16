# Playwright base image (includes browsers & deps)
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install django-ratelimit==4.1.0

# Copy app code
COPY . .

# Collect static assets
RUN python manage.py collectstatic --noinput

EXPOSE 8080

# Run migrations then start gunicorn
CMD ["sh","-c","python manage.py migrate && gunicorn -b 0.0.0.0:8080 --access-logfile - --error-logfile - bonk_skin_search.wsgi:application"]
