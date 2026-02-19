FROM python:3.11-slim

# Chromium 및 드라이버 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Selenium이 시스템 Chromium을 사용하도록 환경변수 설정
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web_app_unified.py .

EXPOSE 8080
CMD ["python3", "web_app_unified.py"]
