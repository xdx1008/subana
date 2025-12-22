import requests
import subprocess
import json
import os
import posixpath
import logging
from database import save_media

# 設定 Log
DATA_DIR = '/app/data'
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

# 確保同時輸出到檔案和 Docker Console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv')

class AlistClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {"Authorization": token, "Content-Type": "application/json"}

    def list_files(self, path):
        try:
            url = f"{self.url}/api/fs/list"
            resp = requests.post(url, headers=self.headers, json={"path": path, "page": 1, "per_page": 0, "refresh": True})
            data = resp.json()
            if data and data.get('code') == 200:
                return data['data']['content']
            else:
                logging.warning(f"無法讀取路徑: {path}, 訊息: {data.get('message')}")
        except Exception as e:
            logging.error(f"API List Error ({path}): {e}")
        return []

    def get_raw_url(self, path):
        try:
            url = f"{self.url}/api/fs/get"
            resp = requests.post(url, headers=self.headers, json={"path": path})
            data = resp.json()
            if data and data.get('code') == 200:
                return data['data']['raw_url']
        except: pass
        return None

def analyze_video_subs(file_url):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0: return "❌ 格式錯誤"
        
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        if not streams: return "🈚 無內嵌字幕"
        
        subs = []
        for i, s in enumerate(streams):
            tags = s.get('tags', {})
            lang = tags.get('language', 'und')
            title = tags.get('title', '')
            codec = s.get('codec_name', 'unknown')
            desc = f"{i+1}. [{lang}] {title} ({codec})"
            subs.append(desc)
        return "\n".join(subs)
    except: return "❌ 分析失敗"

def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 開始全域掃描: {start_cloud_path}")

    # 1. 取得根目錄下的 Drives (01, 02...)
    drives = client.list_files(start_cloud_path)
    if not drives:
        logging.error(f"❌ 根目錄 {start_cloud_path} 讀取失敗或為空！")
        return

    logging.info(f"📂 根目錄下發現 {len(drives)} 個項目")

    # 排序並過濾出資料夾
    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])

    for drive in drive_list:
        drive_id = drive['name']
        drive_full_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"👉 進入 Drive: {drive_id} ({drive_full_path})")

        # 讀取該 Drive 下的內容，尋找 movies 和 tv
        sub_folders = client.list_files(drive_full_path)
        if not sub_folders:
            logging.warning(f"   ⚠️ Drive {drive_id} 是空的")
            continue

        # 建立名稱對照 (轉小寫比對)
        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        
        # --- 處理 Movies ---
        if 'movies' in folder_map:
            real_movie_name = folder_map['movies'] # 可能是 "Movies" 或 "movies"
            movies_path = posixpath.join(drive_full_path, real_movie_name)
            logging.info(f"   🎥 發現電影目錄: {movies_path}")
            
            movie_list = client.list_files(movies_path)
            for m in movie_list:
                if not m['is_dir']: continue
                m_name = m['name']
                m_full_path = posixpath.join(movies_path, m_name)
                
                # 檢查這個電影資料夾內有沒有影片
                m_files = client.list_files(m_full_path)
                video = next((f for f in m_files if f['name'].lower().endswith(VIDEO_EXTS)), None)
                
                if video:
                    logging.info(f"      Analyzing: {m_name}")
                    raw_url = client.get_raw_url(posixpath.join(m_full_path, video['name']))
                    subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
                    
                    save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': subs_text}])
        else:
            logging.info(f"   ℹ️ 跳過: {drive_id} 無 movies 資料夾")

        # --- 處理 TV Shows ---
        if 'tv' in folder_map:
            real_tv_name = folder_map['tv']
            tv_path = posixpath.join(drive_full_path, real_tv_name)
            logging.info(f"   📺 發現劇集目錄: {tv_path}")
            
            tv_list = client.list_files(tv_path)
            for t in tv_list:
                if not t['is_dir']: continue
                t_name = t['name']
                t_full_path = posixpath.join(tv_path, t_name)
                
                # 掃描 Season
                seasons = client.list_files(t_full_path)
                season_data = []
                
                for s in seasons:
                    if not s['is_dir']: continue
                    s_name = s['name']
                    # 簡單過濾，通常季資料夾包含 "Season" 字眼
                    if "Season" not in s_name and "Specials" not in s_name: continue

                    s_path = posixpath.join(t_full_path, s_name)
                    s_files = client.list_files(s_path)
                    
                    # 找第一集影片
                    video = next((f for f in s_files if f['name'].lower().endswith(VIDEO_EXTS)), None)
                    if video:
                        logging.info(f"      Analyzing: {t_name} - {s_name}")
                        raw_url = client.get_raw_url(posixpath.join(s_path, video['name']))
                        subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
                        season_data.append({'season': s_name, 'subs': subs_text})
                
                if season_data:
                    save_media('tv', drive_id, t_name, t_full_path, season_data)
        else:
            logging.info(f"   ℹ️ 跳過: {drive_id} 無 tv 資料夾")

    logging.info("🏁 掃描結束！請查看列表")
