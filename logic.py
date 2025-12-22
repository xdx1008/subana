import requests
import subprocess
import json
import os
import posixpath
import logging

# 設定 Log 格式，輸出到檔案與控制台
LOG_FILE = 'app.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv')

def run_analysis(alist_url, token, start_dir):
    """主執行函式，接收外部傳入的設定參數"""
    logging.info("="*30)
    logging.info(f"🚀 任務啟動，掃描目標: {start_dir}")

    # --- 內部輔助函式 (使用閉包捕獲目前的 url/token) ---
    def alist_api(endpoint, method="POST", body=None):
        url = f"{alist_url}/api/fs/{endpoint}"
        headers = {"Authorization": token, "Content-Type": "application/json"}
        try:
            if method == "POST":
                resp = requests.post(url, headers=headers, json=body)
            else:
                resp = requests.get(url, headers=headers, params=body)
            return resp.json()
        except Exception as e:
            logging.error(f"API 連線錯誤: {e}")
            return None

    def get_raw_url(path):
        data = alist_api("get", body={"path": path})
        if data and data.get('code') == 200:
            return data['data']['raw_url']
        return None

    def analyze_video(file_url):
        cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0: return ["❌ 分析失敗 (Format Error)"]
            if not result.stdout: return None # 無輸出視為無字幕軌

            info = json.loads(result.stdout)
            streams = info.get('streams', [])
            if not streams: return None
            
            subs = []
            for s in streams:
                tags = s.get('tags', {})
                lang = tags.get('language', 'und')
                title = tags.get('title', '')
                codec = s.get('codec_name', 'unknown')
                desc = f"[{lang}]"
                if title: desc += f" {title}"
                desc += f" ({codec})"
                subs.append(desc)
            return subs
        except subprocess.TimeoutExpired: return ["⏱️ 分析超時"]
        except Exception as e: return [f"❌ 錯誤: {str(e)}"]

    def upload_report(path, content):
        url = f"{alist_url}/api/fs/put"
        headers = {"Authorization": token, "File-Path": requests.utils.quote(path), "Content-Type": "text/plain"}
        try:
            resp = requests.put(url, headers=headers, data=content.encode('utf-8'))
            return resp.json().get('code') == 200
        except: return False

    # --- 遞迴處理邏輯 ---
    def process_folder(current_path):
        logging.info(f"📂 掃描目錄: {current_path}")
        list_data = alist_api("list", body={"path": current_path, "page": 1, "per_page": 0, "refresh": True})
        
        if not list_data or list_data.get('code') != 200:
            logging.warning(f"   ⚠️ 無法讀取目錄 (可能權限不足或路徑錯誤): {current_path}")
            return

        items = list_data['data']['content']
        if not items: return

        sub_folders = [i for i in items if i['is_dir']]
        videos = [i for i in items if not i['is_dir'] and i['name'].lower().endswith(VIDEO_EXTS)]

        # 1. 先遞迴進入子目錄
        for folder in sub_folders:
            next_path = posixpath.join(current_path, folder['name'])
            process_folder(next_path)

        # 2. 處理當前目錄的影片
        if videos:
            logging.info(f"🎬 在 {current_path} 發現 {len(videos)} 部影片，開始分析...")
            
            report_lines = []
            report_lines.append(f"📁 目錄: {current_path}")
            report_lines.append("=" * 60)
            
            for vid in videos:
                full_path = posixpath.join(current_path, vid['name'])
                raw_url = get_raw_url(full_path)
                sub_info = ""
                
                if raw_url:
                    subs = analyze_video(raw_url)
                    if subs:
                        sub_info = ", ".join(subs)
                        logging.info(f"   ✅ 已分析: {vid['name']}")
                    else:
                        sub_info = "🈚 無內嵌字幕"
                        logging.info(f"   🈚 無字幕: {vid['name']}")
                else:
                    sub_info = "❌ 無法取得連結"
                    logging.warning(f"   ❌ 連結失敗: {vid['name']}")
                
                report_lines.append(f"{vid['name']:<40} | {sub_info}")
            
            # 上傳報告
            parent_dir = posixpath.dirname(current_path)
            folder_name = posixpath.basename(current_path) or "Root"
            report_filename = f"{folder_name}_MediaInfo.txt"
            upload_path = posixpath.join(parent_dir, report_filename)
            
            if upload_report(upload_path, "\n".join(report_lines)):
                logging.info(f"📤 報告成功上傳至: {upload_path}")
            else:
                logging.error(f"❌ 報告上傳失敗: {upload_path}")
            logging.info("-" * 30)

    # 開始執行
    try:
        process_folder(start_dir)
        logging.info("🏁 任務結束")
    except Exception as e:
        logging.critical(f"執行過程中發生未預期的錯誤: {e}")
