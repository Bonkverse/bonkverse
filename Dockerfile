# Use an official Python runtime as a parent image
#
FROM python:3.12

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y libpq-dev libgl1

# Install Playwright and its dependencies
RUN pip install playwright
RUN playwright install --with-deps

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Collect static files
RUN python manage.py collectstatic --noinput

# Set the command to run the application
CMD ["sh", "-c", "python manage.py migrate && gunicorn -b 0.0.0.0:8080 --access-logfile - --error-logfile - bonk_skin_search.wsgi:application"]

