# Keep in step with PYTHON_VERSION in .github/workflows/ci.yml.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libjpeg62-turbo-dev \
    libpng-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# collectstatic needs settings to load, but the build has no secrets: a dummy
# key for this one step only (settings refuse it when ENV=production).
RUN rm -rf staticfiles && ENV=build DJANGO_ALLOW_DUMMY_SECRET=true python manage.py collectstatic --noinput --clear

EXPOSE 8080

# Workers, threads, port and timeouts live in gunicorn.conf.py.
CMD ["sh", "-c", "python manage.py migrate && gunicorn -c gunicorn.conf.py bonk_skin_search.wsgi:application"]
