# 使用輕量級 Python 映像檔
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# 1. 安裝系統依賴 (FFmpeg 是必須的)
# 清理緩存以減小映像檔體積
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 2. 複製並安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 複製所有程式碼檔案到容器內
COPY . .

# 4. 給予啟動腳本執行權限
RUN chmod +x start.sh

# 5. 設定環境變數，確保 Python Log 即時輸出
ENV PYTHONUNBUFFERED=1

# 6. 宣告會使用的連接埠 (僅供文件說明用，實際需在 compose 對映)
EXPOSE 8501

# 7. 容器啟動時執行的指令
CMD ["./start.sh"]
