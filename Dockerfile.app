# Use a slim Python base image
FROM python:3.10-slim

# Install necessary packages including Tor and binary dependencies for Selenium
RUN apt-get update && apt-get install -y unzip curl && \
    curl -Lo "/tmp/chromedriver-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.94/linux64/chromedriver-linux64.zip" && \
    curl -Lo "/tmp/chrome-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.94/linux64/chrome-linux64.zip" && \
    unzip /tmp/chromedriver-linux64.zip -d /opt/ && \
    unzip /tmp/chrome-linux64.zip -d /opt/

# Install necessary system  packages and install additional packages for Chrome to run (also in AWS Lambda)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    gcc \
    unzip \
    curl \
    wget \
    gnupg \
    libasound2 \
    libgbm-dev \
    libgtk-3-0 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    xdg-utils

# Install Python packages
RUN pip install selenium==4.18.1 \
    && pip install requests~=2.32.3 'requests[socks]' \
    && pip install beautifulsoup4~=4.12.3 \
    && pip install aiohttp~=3.10.3 \
    && pip install aiofiles~=24.1.0 \
    && pip install aiohttp_socks~=0.9.0 \
    && pip install fastapi uvicorn~=0.30.6 \
    && pip install python-jose[cryptography]  \
    && pip install argon2-cffi \
    && pip install passlib[argon2]==1.7.4 \
    && pip install motor~=3.6.0 \
    && pip install jinja2~=3.1.4 \
    && pip install psutil~=6.0.0 \
    && pip install APScheduler~=3.10.4 \
    && pip install python-multipart~=0.0.10 \
    && pip install pydantic-settings~=2.5.2

# Set the working directory
WORKDIR /app

# Copy the application code
COPY . /app

# Expose port 8000 (default for Uvicorn)
EXPOSE 8000

# Start the FastAPI application with Uvicorn
CMD ["sh", "-c", "sleep 10 && uvicorn main:app --host 0.0.0.0 --port 8000"]
