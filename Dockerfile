# Install binary dependencies for Selenium
FROM python:3.10-slim as build
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
RUN pip install selenium==4.18.1 && pip install requests~=2.32.3 && pip install requests[socks] \
    && pip install beautifulsoup4~=4.12.3 && pip install aiohttp~=3.10.3 && pip install aiofiles~=24.1.0 \
    && pip install aiohttp_socks~=0.9.0

# Set Tor to listen on 9050
RUN echo "SocksPort 127.0.0.1:9050" >> /etc/tor/torrc

# Set the working directory
WORKDIR /app

# Copy scraper script (initial copy, in case volume mount fails)
COPY scrape.py ./
