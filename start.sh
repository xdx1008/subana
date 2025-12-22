#!/bin/bash

# 建立空的設定檔與日誌檔 (如果不存在)，避免掛載權限問題
touch config.json
touch app.log

echo "啟動背景 Worker..."
python worker.py &

echo "啟動 Streamlit Web UI..."
# 使用 --server.address=0.0.0.0 讓外部可以訪問
streamlit run app.py --server.port=8501 --server.address=0.0.0.0
