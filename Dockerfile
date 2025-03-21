FROM python:3.12-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Start server (adjust as needed)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "bonk_skin_search.wsgi:application"]
