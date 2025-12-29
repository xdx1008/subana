# ==========================================
# 第一階段：Builder (負責下載與編譯)
# ==========================================
FROM python:3.10-slim-bookworm as builder

# 設定環境變數
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# 安裝下載工具 (curl, unzip)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl unzip && \
    rm -rf /var/lib/apt/lists/*

# 1. 下載並安裝 Rclone (只提取二進制檔)
# 使用官方腳本下載，解壓後只保留執行檔
RUN curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
    unzip rclone-current-linux-amd64.zip && \
    mv rclone-*-linux-amd64/rclone /usr/bin/rclone && \
    chmod +x /usr/bin/rclone

# 2. 建置 Python 依賴環境
COPY requirements.txt .
# 安裝依賴到 /install 目錄，使用 --user 或 --target 也可以，但 venv 更乾淨
RUN python -m venv /opt/venv
# 啟用 venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==========================================
# 第二階段：Final (最終執行環境)
# ==========================================
FROM python:3.10-slim-bookworm

WORKDIR /app

# 設定環境變數
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# 1. 安裝執行期必要的系統套件
# ffmpeg: 用於 ffprobe 分析影片資訊 (Subana 需要)
# ca-certificates: 用於 HTTPS 連線
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. 從 Builder 階段複製檔案
# 複製 Python 虛擬環境
COPY --from=builder /opt/venv /opt/venv
# 複製 Rclone 執行檔
COPY --from=builder /usr/bin/rclone /usr/bin/rclone

# 3. 複製程式碼
# 由於有 .dockerignore，這裡只會複製必要的 .py 和 .json 檔
COPY . .

# 4. 初始化資料目錄
# 建立 /app/data 並宣告為 Volume
RUN mkdir -p /app/data
VOLUME /app/data

# 5. 開放埠口
EXPOSE 8501

# 6. 健康檢查 (可選)
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

# 7. 啟動指令
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
