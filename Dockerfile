# 第一階段：取得靜態編譯的 FFmpeg/FFprobe (這是一個超小的映像檔)
FROM mwader/static-ffmpeg:6.0 AS ffmpeg_source

# 第二階段：建立我們的主程式
FROM python:3.9-slim

# 設定工作目錄
WORKDIR /app

# --- 瘦身關鍵 1：不使用 apt 安裝 ffmpeg ---
# 直接從第一階段複製編譯好的執行檔到我們的環境中
# 我們只需要 ffprobe 來分析，但為了保險起見把 ffmpeg 也複製過來
COPY --from=ffmpeg_source /ffmpeg /usr/local/bin/
COPY --from=ffmpeg_source /ffprobe /usr/local/bin/

# --- 瘦身關鍵 2：只安裝必要的 Python 套件 ---
COPY requirements.txt .
RUN echo "Cache bust: v7.5"
# --no-cache-dir 可以避免 pip 下載的暫存檔佔用空間
RUN pip install --no-cache-dir -r requirements.txt

# 複製程式碼
COPY . .

# 給予腳本權限
RUN chmod +x start.sh

# 設定環境變數
ENV PYTHONUNBUFFERED=1

# 宣告 Port
EXPOSE 8501

# 啟動
CMD ["./start.sh"]
