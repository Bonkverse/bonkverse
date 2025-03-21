# Use an official Python runtime as a parent image
#
FROM python:3.12

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y libpq-dev

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set the command to run the application
CMD ["gunicorn", "-b", "0.0.0.0:8000", "bonk_skin_search.wsgi:application"]
