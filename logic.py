import requests
import subprocess
import json
import os
import posixpath
import logging
from database import save_media, check_media_exists, get_media_by_id

# 設定 Log
DATA_DIR = '/app/data'
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

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

# --- 核心處理邏輯 (提取出來共用) ---

def process_movie_item(client, drive_id, m_name, m_full_path):
    """處理單一電影資料夾"""
    logging.info(f"   🎥 分析電影: {m_name}")
    files = client.list_files(m_full_path)
    video = next((f for f in files if f['name'].lower().endswith(VIDEO_EXTS)), None)
    
    if video:
        raw_url = client.get_raw_url(posixpath.join(m_full_path, video['name']))
        subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': subs_text}])
        return True
    else:
        logging.warning(f"      ⚠️ {m_name} 找不到影片檔")
        return False

def process_tv_item(client, drive_id, t_name, t_full_path):
    """處理單一劇集資料夾"""
    logging.info(f"   📺 分析劇集: {t_name}")
    seasons = client.list_files(t_full_path)
    season_data = []
    
    for s in seasons:
        if not s['is_dir']: continue
        s_name = s['name']
        if "Season" not in s_name and "Specials" not in s_name: continue

        s_path = posixpath.join(t_full_path, s_name)
        s_files = client.list_files(s_path)
        
        # 找第一集影片
        video = next((f for f in s_files if f['name'].lower().endswith(VIDEO_EXTS)), None)
        if video:
            logging.info(f"      Analyzing: {s_name}")
            raw_url = client.get_raw_url(posixpath.join(s_path, video['name']))
            subs_text = analyze_video_subs(raw_url) if raw_url else "❌ 無法取得連結"
            season_data.append({'season': s_name, 'subs': subs_text})
    
    if season_data:
        save_media('tv', drive_id, t_name, t_full_path, season_data)
        return True
    return False

# --- 主任務 ---

def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    """全域掃描：會跳過已存在的項目"""
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 開始全域掃描 (跳過已存在): {start_cloud_path}")

    drives = client.list_files(start_cloud_path)
    if not drives:
        logging.error("❌ 根目錄讀取失敗")
        return

    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])

    for drive in drive_list:
        drive_id = drive['name']
        drive_full_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"👉 Drive: {drive_id}")

        sub_folders = client.list_files(drive_full_path)
        if not sub_folders: continue
        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        
        # Movies
        if 'movies' in folder_map:
            movies_path = posixpath.join(drive_full_path, folder_map['movies'])
            for m in client.list_files(movies_path):
                if not m['is_dir']: continue
                m_path = posixpath.join(movies_path, m['name'])
                
                # 🔥 關鍵修改：檢查是否存在
                if check_media_exists(m_path):
                    logging.info(f"   ⏭️ 跳過 (已存在): {m['name']}")
                    continue
                
                process_movie_item(client, drive_id, m['name'], m_path)

        # TV
        if 'tv' in folder_map:
            tv_path = posixpath.join(drive_full_path, folder_map['tv'])
            for t in client.list_files(tv_path):
                if not t['is_dir']: continue
                t_path = posixpath.join(tv_path, t['name'])
                
                # 🔥 關鍵修改：檢查是否存在
                if check_media_exists(t_path):
                    logging.info(f"   ⏭️ 跳過 (已存在): {t['name']}")
                    continue
                
                process_tv_item(client, drive_id, t['name'], t_path)

    logging.info("🏁 掃描結束！")

def run_single_refresh(alist_url, token, media_id):
    """單一項目強制刷新"""
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    
    if not row:
        logging.error("❌ 找不到該媒體 ID")
        return

    logging.info(f"🔄 [手動刷新] {row['name']} ({row['type']})")
    
    success = False
    if row['type'] == 'movie':
        success = process_movie_item(client, row['drive_id'], row['name'], row['full_path'])
    elif row['type'] == 'tv':
        success = process_tv_item(client, row['drive_id'], row['name'], row['full_path'])
        
    if success:
        logging.info("✅ 刷新完成")
    else:
        logging.error("❌ 刷新失敗 (可能檔案已移動或 API 錯誤)")
