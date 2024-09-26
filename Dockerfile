# Install main python image
FROM python:3.10-slim as build

# Install necessary packages including Tor and binary dependencies for Selenium
RUN apt-get update && apt-get install -y unzip curl tor && \
    curl -Lo "/tmp/chromedriver-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.94/linux64/chromedriver-linux64.zip" && \
    curl -Lo "/tmp/chrome-linux64.zip" "https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.94/linux64/chrome-linux64.zip" && \
    unzip /tmp/chromedriver-linux64.zip -d /opt/ && \
    unzip /tmp/chrome-linux64.zip -d /opt/

# Install additional packages for Chrome to run (also in AWS Lambda)
RUN apt-get install -y --no-install-recommends \
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
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

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
    && pip install python-multipart~=0.0.10

# Set Tor to listen on 9050
RUN echo "SocksPort 127.0.0.1:9050" >> /etc/tor/torrc

# Set the working directory
WORKDIR /app

# Copy your application code
COPY . /app

# Expose port 8000 for FastAPI
EXPOSE 8000

# CMD is set to start Tor and Uvicorn, sleep for 5 seconds to allow Mongodb to start
CMD ["sh", "-c", "sleep 5 && service tor start && uvicorn main:app --host 0.0.0.0 --port 8000"]
