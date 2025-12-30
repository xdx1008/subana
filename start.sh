#!/bin/bash

# 1. 確保資料目錄存在 (避免 Volume 掛載時權限問題或目錄缺失)
mkdir -p /app/data

# 2. (選用) 檢查 Rclone 設定檔目錄
# 即使您在 UI 指定了路徑，建立預設目錄是個好習慣
mkdir -p /root/.config/rclone

# 3. 顯示啟動訊息 (方便 Debug)
echo "🚀 Subana (NiceGUI) is starting..."
echo "📂 Working Directory: $(pwd)"
echo "🐍 Python Executable: $(which python)"

# 4. 啟動應用程式
# 使用 exec 可以讓 python process 取代 shell 成為 PID 1，
# 這樣 Docker stop 時應用程式才能正確接收關閉訊號。
exec python main.py
