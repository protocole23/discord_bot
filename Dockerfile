FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright(크롬) 실행에 필요한 리눅스 시스템 라이브러리 + 브라우저 설치
RUN playwright install-deps chromium && playwright install chromium

COPY . .

CMD ["python", "bot.py"]
