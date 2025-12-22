import time
import json
import os
import logging
from logic import run_library_scan

DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
logging.basicConfig(level=logging.INFO, format='[Worker] %(asctime)s %(message)s')

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: pass
    return None

logging.info("Worker Started")

while True:
    config = load_config()
    # 這裡可以加入判斷是否要自動執行的邏輯
    # 為了簡單起見，這裡預設每 24 小時掃描一次，或者您可以在 UI 加一個 auto_scan 開關
    if config and config.get("auto_run", False):
        logging.info("Auto Scan Started")
        try:
            run_library_scan(config['url'], config['token'], config['path'])
        except Exception as e:
            logging.error(f"Scan Error: {e}")
        
        # 休息時間 (例如 12 小時 = 43200 秒)
        time.sleep(config.get("interval", 43200))
    else:
        time.sleep(60)
