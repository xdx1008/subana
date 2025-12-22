import time
import json
import os
import logging
from logic import run_analysis

# --- 修改點：路徑設定 ---
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

# 確保目錄存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Worker 輸出到 Console (這樣可以在 Docker logs 看到)
logging.basicConfig(level=logging.INFO, format='[Worker] %(asctime)s - %(message)s')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"讀取設定檔失敗: {e}")
    return None

logging.info("背景排程服務已啟動。")

while True:
    config = load_config()
    
    if config and config.get("auto_run", False):
        url = config.get("url")
        token = config.get("token")
        path = config.get("path")
        interval = config.get("interval", 3600)

        if url and token and path:
            logging.info(f"⏰ 自動執行觸發 (間隔 {interval}s)")
            try:
                run_analysis(url, token, path)
            except Exception as e:
                logging.error(f"執行錯誤: {e}")
            
            logging.info(f"💤 休眠 {interval} 秒...")
            time.sleep(interval)
        else:
            logging.warning("設定不完整，等待修正...")
            time.sleep(60)
            
    else:
        time.sleep(30)
