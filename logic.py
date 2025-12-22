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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
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
        except Exception as e:
            logging.error(f"API List Error: {e}")
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
    """回傳格式化的字幕列表字串"""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0 or not result.stdout: return None
        
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        if not streams: return "🈚 無內嵌字幕"
        
        subs = []
        for i, s in enumerate(streams):
            tags = s.get('tags', {})
            lang = tags.get('language', 'und')
            title = tags.get('title', '')
            codec = s.get('codec_name', 'unknown')
            # 格式: 1. [chi] 繁體中文 (ass)
            desc = f"{i+1}. [{lang}] {title} ({codec})"
            subs.append(desc)
        return "\n".join(subs) # 用換行符號分隔
    except: return "❌ 分析失敗"

def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    """
    針對結構化目錄進行掃描：
    /Cloud/{01-24}/movies
    /Cloud/{01-24}/tv
    """
    client = AlistClient(alist_url, token)
    logging.info("🚀 開始媒體庫掃描...")

    # 1. 取得 /Cloud 底下的所有 drive (01, 02... 24)
    drives = client.list_files(start_cloud_path)
    if not drives:
        logging.error("無法讀取根目錄，請檢查設定")
        return

    # 排序 01, 02...
    drives = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])

    for drive in drives:
        drive_id = drive['name']
        drive_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"📂 正在掃描硬碟: {drive_id}")

        # === 處理 Movies ===
        movies_path = posixpath.join(drive_path, 'movies')
        movie_folders = client.list_files(movies_path)
        
        for m in movie_folders:
            if not m['is_dir']: continue
            logging.info(f"   🎥 分析電影: {m['name']}")
            
            # 找該資料夾內的第一個影片檔
            m_path = posixpath.join(movies_path, m['name'])
            files = client.list_files(m_path)
            video = next((f for f in files if f['name'].lower().endswith(VIDEO_EXTS)), None)
            
            if video:
                raw_url = client.get_raw_url(posixpath.join(m_path, video['name']))
                subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
                
                # 存入 DB
                save_media('movie', drive_id, m['name'], m_path, [{'season': 'Movie', 'subs': subs_text}])

        # === 處理 TV Shows ===
        tv_path = posixpath.join(drive_path, 'tv')
        tv_folders = client.list_files(tv_path)
        
        for t in tv_folders:
            if not t['is_dir']: continue
            logging.info(f"   📺 分析劇集: {t['name']}")
            t_path = posixpath.join(tv_path, t['name'])
            
            # 取得 Season 資料夾
            seasons = client.list_files(t_path)
            season_data = []
            
            for s in seasons:
                if not s['is_dir']: continue # 只看資料夾 (Season XX)
                s_path = posixpath.join(t_path, s['name'])
                
                # 找該季的第一個影片檔 (假設整季字幕一樣)
                s_files = client.list_files(s_path)
                video = next((f for f in s_files if f['name'].lower().endswith(VIDEO_EXTS)), None)
                
                if video:
                    raw_url = client.get_raw_url(posixpath.join(s_path, video['name']))
                    subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
                    season_data.append({'season': s['name'], 'subs': subs_text})
            
            if season_data:
                save_media('tv', drive_id, t['name'], t_path, season_data)

    logging.info("🏁 媒體庫掃描完成！")
