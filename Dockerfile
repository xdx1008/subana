# --- Stage 1: Build Frontend ---
FROM node:18-alpine as build-stage
WORKDIR /app/frontend
# 複製 package.json 和 lock 檔
COPY frontend/package*.json ./
# 安裝依賴
RUN npm install
# 複製前端源碼
COPY frontend/ .
# 編譯 (這會產生 dist 資料夾)
RUN npm run build

# --- Stage 2: Python Backend ---
FROM python:3.10-slim
WORKDIR /app

# 安裝系統工具
RUN apt-get update && apt-get install -y \
    curl unzip ffmpeg \
    && curl https://rclone.org/install.sh | bash \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製後端代碼
COPY logic.py database.py server.py ./

# [關鍵步驟] 從第一階段複製編譯好的前端檔案到 /app/static
# 注意：Vite 預設輸出到 dist，我們要把它改名為 static 放入後端容器
COPY --from=build-stage /app/frontend/dist /app/static

# 建立數據目錄
RUN mkdir -p /app/data

EXPOSE 8080

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]