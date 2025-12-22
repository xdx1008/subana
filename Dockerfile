FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start.sh

# 宣告這是一個掛載點
VOLUME /app/data

ENV PYTHONUNBUFFERED=1
EXPOSE 8501

CMD ["./start.sh"]
