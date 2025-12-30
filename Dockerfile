# 建立一個包含 FFmpeg 和 Python 的基底映像
FROM python:3.10-slim

# 安裝系統工具 (FFmpeg, Rclone 依賴, curl, tzdata)
RUN apt-get update && \
    apt-get install -y ffmpeg curl unzip tzdata && \
    rm -rf /var/lib/apt/lists/*

# 安裝 Rclone (官方腳本)
RUN curl https://rclone.org/install.sh | bash

# 設定工作目錄
WORKDIR /app

# 複製需求檔並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製所有程式碼
COPY . /app

# 🔥 [關鍵] 賦予 start.sh 執行權限
RUN chmod +x /app/start.sh

# 設定環境變數
ENV TZ=Asia/Taipei
# 讓 Python 輸出不被緩衝 (Log 會即時顯示)
ENV PYTHONUNBUFFERED=1 

# 暴露 NiceGUI 預設端口
EXPOSE 8080

# 🔥 [關鍵] 使用 start.sh 作為啟動入口
CMD ["/app/start.sh"]
