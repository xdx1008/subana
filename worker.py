import time
import json
import os
import logging
from logic import run_analysis

CONFIG_FILE = 'config.json'
# Worker 自己也需要 Log，這裡簡單設定輸出到 console (Docker logs)
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
            logging.info(f"⏰ 自動排程觸發，準備執行任務 (間隔: {interval}秒)")
            try:
                # 呼叫核心邏輯
                run_analysis(url, token, path)
            except Exception as e:
                logging.error(f"任務執行發生錯誤: {e}")
            
            logging.info(f"💤 任務結束，進入休眠 {interval} 秒...")
            time.sleep(interval)
        else:
            logging.warning("⚠️ 自動執行已啟用，但設定檔參數不完整 (URL/Token/Path)，等待修正...")
            time.sleep(60) # 設定不完整時，每分鐘檢查一次
            
    else:
        # 如果沒開自動執行，就每 30 秒檢查一次設定檔狀態
        # logging.debug("自動執行未啟用，待機中...") 
        time.sleep(30)
