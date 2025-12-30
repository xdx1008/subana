# 建立一個包含 FFmpeg 和 Python 的基底映像
FROM python:3.10-slim

# 安裝系統工具 (FFmpeg, Rclone 依賴)
RUN apt-get update && \
    apt-get install -y ffmpeg curl unzip && \
    rm -rf /var/lib/apt/lists/*

# 安裝 Rclone
RUN curl https://rclone.org/install.sh | bash

# 設定工作目錄
WORKDIR /app

# 複製需求檔並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . /app

# 設定時區 (確保 Log 時間正確)
ENV TZ=Asia/Taipei

# 暴露 NiceGUI 預設端口
EXPOSE 8080

# 🔥 [v40.0 Change] 改為直接執行 main.py
CMD ["python", "main.py"]
