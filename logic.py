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
# 定義支援的外部字幕格式
SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')

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
    """分析內嵌字幕"""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0: return "❌ [內嵌] 格式讀取錯誤"
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        
        subs = []
        # 1. 處理內嵌字幕
        if streams:
            for i, s in enumerate(streams):
                tags = s.get('tags', {})
                lang = tags.get('language', 'und')
                title = tags.get('title', '')
                codec = s.get('codec_name', 'unknown')
                desc = f"[內嵌] {i+1}. {lang} - {title} ({codec})"
                subs.append(desc)
        
        return subs # 回傳 List
    except: return ["❌ [內嵌] 分析超時或失敗"]

def find_external_subs(video_name, all_files):
    """
    比對外部字幕：
    video_name: Movie.2024.mkv
    all_files: 該資料夾下的所有檔案列表 (API return)
    return: List of strings (e.g., "[外部] Movie.2024.chi.srt")
    """
    found_subs = []
    # 取得檔名 (不含副檔名)，例如 "Movie.2024"
    video_base = os.path.splitext(video_name)[0]
    
    for f in all_files:
        if f['is_dir']: continue
        fname = f['name']
        
        # 檢查是否為字幕檔
        if fname.lower().endswith(SUB_EXTS):
            # 檢查是否包含影片檔名 (這是最寬鬆的匹配，通常是 startswith)
            # 例如: video_base="S01E01", sub="S01E01.chi.srt" -> Match
            if fname.startswith(video_base):
                found_subs.append(f"📁 [外部] {fname}")
                
    return found_subs

# --- 核心處理邏輯 ---

def process_movie_item(client, drive_id, m_name, m_full_path):
    logging.info(f"   🎥 分析電影: {m_name}")
    # 取得該資料夾下所有檔案
    files = client.list_files(m_full_path)
    
    if not files:
        logging.warning(f"      ⚠️ 資料夾為空: {m_name}")
        return False

    video = next((f for f in files if f['name'].lower().endswith(VIDEO_EXTS)), None)
    
    if video:
        # 1. 分析內嵌
        raw_url = client.get_raw_url(posixpath.join(m_full_path, video['name']))
        embedded_subs = analyze_video_subs(raw_url) if raw_url else ["❌ 無法取得連結"]
        
        # 2. 搜尋外部字幕 (傳入所有檔案列表進行比對)
        external_subs = find_external_subs(video['name'], files)
        
        # 3. 合併結果
        all_subs_info = external_subs + embedded_subs
        if not all_subs_info: all_subs_info = ["🈚 無任何字幕"]
        
        final_text = "\n".join(all_subs_info)
        
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': final_text}])
        return True
    else:
        logging.warning(f"      ⚠️ {m_name} 找不到影片檔")
        return False

def process_tv_item(client, drive_id, t_name, t_full_path):
    logging.info(f"   📺 分析劇集: {t_name}")
    seasons = client.list_files(t_full_path)
    
    if not seasons:
        logging.warning(f"      ⚠️ 資料夾為空: {t_name}")
        return False

    season_data = []
    
    for s in seasons:
        if not s['is_dir']: continue
        s_name = s['name']
        if "Season" not in s_name and "Specials" not in s_name: continue

        s_path = posixpath.join(t_full_path, s_name)
        # 取得該季資料夾下的「所有檔案」
        s_files = client.list_files(s_path)
        
        if not s_files: continue

        # 找第一集影片來代表整季 (通常整季字幕狀況相同)
        # 這裡我們只分析第一集，但會掃描第一集的外部字幕
        video = next((f for f in s_files if f['name'].lower().endswith(VIDEO_EXTS)), None)
        
        if video:
            logging.info(f"      Analyzing: {s_name} (Sample: {video['name']})")
            
            # 1. 內嵌
            raw_url = client.get_raw_url(posixpath.join(s_path, video['name']))
            embedded_subs = analyze_video_subs(raw_url) if raw_url else ["❌ 無法取得連結"]
            
            # 2. 外部 (針對這一個影片檔尋找對應字幕)
            external_subs = find_external_subs(video['name'], s_files)
            
            # 3. 合併
            all_subs_info = external_subs + embedded_subs
            if not all_subs_info: all_subs_info = ["🈚 無任何字幕"]
            
            final_text = "\n".join(all_subs_info)
            season_data.append({'season': s_name, 'subs': final_text})
    
    if season_data:
        save_media('tv', drive_id, t_name, t_full_path, season_data)
        return True
    return False

# --- 主任務 ---

def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 開始全域掃描: {start_cloud_path}")

    drives = client.list_files(start_cloud_path)
    if not drives:
        logging.error("❌ 根目錄讀取失敗或為空")
        return

    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])

    for drive in drive_list:
        drive_id = drive['name']
        drive_full_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"👉 Drive: {drive_id}")

        sub_folders = client.list_files(drive_full_path)
        if not sub_folders:
            logging.info(f"   ℹ️ Drive {drive_id} 是空的，跳過")
            continue

        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        
        # Movies
        if 'movies' in folder_map:
            real_name = folder_map['movies']
            movies_path = posixpath.join(drive_full_path, real_name)
            movie_list = client.list_files(movies_path)
            
            if not movie_list:
                logging.info(f"   ℹ️ {real_name} 資料夾是空的，跳過")
            else:
                logging.info(f"   🎥 掃描電影 ({len(movie_list)})")
                for m in movie_list:
                    if not m['is_dir']: continue
                    m_path = posixpath.join(movies_path, m['name'])
                    if check_media_exists(m_path):
                        logging.info(f"   ⏭️ 跳過 (已存在): {m['name']}")
                        continue
                    process_movie_item(client, drive_id, m['name'], m_path)

        # TV
        if 'tv' in folder_map:
            real_name = folder_map['tv']
            tv_path = posixpath.join(drive_full_path, real_name)
            tv_list = client.list_files(tv_path)
            
            if not tv_list:
                logging.info(f"   ℹ️ {real_name} 資料夾是空的，跳過")
            else:
                logging.info(f"   📺 掃描劇集 ({len(tv_list)})")
                for t in tv_list:
                    if not t['is_dir']: continue
                    t_path = posixpath.join(tv_path, t['name'])
                    if check_media_exists(t_path):
                        logging.info(f"   ⏭️ 跳過 (已存在): {t['name']}")
                        continue
                    process_tv_item(client, drive_id, t['name'], t_path)

    logging.info("🏁 掃描結束！")

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row:
        logging.error("❌ 找不到該媒體 ID")
        return

    logging.info(f"🔄 [手動刷新] {row['name']}")
    success = False
    if row['type'] == 'movie':
        success = process_movie_item(client, row['drive_id'], row['name'], row['full_path'])
    elif row['type'] == 'tv':
        success = process_tv_item(client, row['drive_id'], row['name'], row['full_path'])
        
    if success: logging.info("✅ 刷新完成")
    else: logging.error("❌ 刷新失敗")
