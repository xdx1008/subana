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

def has_chinese_embedded(file_url):
    """
    分析內嵌字幕 (當沒有外部字幕時才會執行此函式)
    """
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
    try:
        # 設定 20秒 超時
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0: return False, "Format Error"
        
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        
        # 內嵌字幕關鍵字
        keywords = ['chi', 'zho', 'chinese', 'cht', 'chs', '繁體', '简体', 'mandarin', 'zh-tw', 'zh-cn']
        
        track_info = []
        has_chi = False
        
        for i, s in enumerate(streams):
            tags = s.get('tags', {})
            lang = tags.get('language', 'und').lower()
            title = tags.get('title', '').lower()
            codec = s.get('codec_name', 'unknown')
            
            # 判斷是否為中文
            is_this_chi = any(k in lang for k in keywords) or any(k in title for k in keywords)
            if is_this_chi: has_chi = True
            
            track_info.append(f"{lang}({codec})")
            
        return has_chi, ", ".join(track_info)
    except: return False, "Analyze Timeout"

def check_external_sub(video_name, all_files):
    """
    🔥 核心邏輯：檢查同目錄下是否有對應的外部字幕
    video_name: S01E01.mkv
    all_files: 目錄下的檔案列表
    """
    # 取得檔名主體 (S01E01)
    video_base = os.path.splitext(video_name)[0]
    
    for f in all_files:
        if f['is_dir']: continue
        fname = f['name']
        
        # 必須是字幕副檔名
        if fname.lower().endswith(SUB_EXTS):
            # 必須包含影片主檔名 (例如 S01E01.chi.srt 包含 S01E01)
            if video_base in fname:
                return True, fname
                
    return False, None

def process_folder_videos(client, full_path, all_files):
    """
    處理資料夾內的所有影片
    邏輯：外部字幕優先 -> 有則跳過 -> 無則檢查內嵌
    """
    results = []
    video_files = [f for f in all_files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    video_files.sort(key=lambda x: x['name'])

    for vid in video_files:
        ep_name = vid['name']
        logging.info(f"      Checking: {ep_name} ...")
        
        # === 1. 優先檢查外部字幕 ===
        has_ext, ext_name = check_external_sub(ep_name, all_files)
        
        if has_ext:
            logging.info(f"         ✅ 找到外部字幕: {ext_name} (跳過內嵌分析)")
            results.append({
                "name": ep_name,
                "status": "ok",
                "type": "external",
                "detail": f"[外部] {ext_name}" # 加上標記讓 app.py 識別
            })
            # 🔥 關鍵：找到外部字幕就直接換下一集，不跑下面的 ffprobe
            continue 
        
        # === 2. 無外部字幕，開始分析內嵌 ===
        logging.info(f"         ⚠️ 無外部字幕，開始分析內嵌...")
        raw_url = client.get_raw_url(posixpath.join(full_path, ep_name))
        
        if raw_url:
            has_emb, track_info = has_chinese_embedded(raw_url)
            if has_emb:
                logging.info(f"         ✅ 內嵌包含中文")
                results.append({
                    "name": ep_name,
                    "status": "ok",
                    "type": "embedded",
                    "detail": f"[內嵌] {track_info}"
                })
            else:
                logging.warning(f"         ❌ 缺字幕")
                results.append({
                    "name": ep_name,
                    "status": "missing",
                    "detail": track_info if track_info else "No subs found"
                })
        else:
            results.append({"name": ep_name, "status": "error", "detail": "Link Error"})
                
    return results

# --- 處理電影 ---
def process_movie_item(client, drive_id, m_name, m_full_path):
    logging.info(f"   🎥 分析電影: {m_name}")
    files = client.list_files(m_full_path)
    if not files: return False

    episodes = process_folder_videos(client, m_full_path, files)
    
    if episodes:
        json_str = json.dumps(episodes)
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': json_str}])
        return True
    return False

# --- 處理劇集 ---
def process_tv_item(client, drive_id, t_name, t_full_path):
    logging.info(f"   📺 分析劇集: {t_name}")
    seasons = client.list_files(t_full_path)
    if not seasons: return False

    season_data = []
    
    for s in seasons:
        if not s['is_dir']: continue
        s_name = s['name']
        if "Season" not in s_name and "Specials" not in s_name: continue

        s_path = posixpath.join(t_full_path, s_name)
        s_files = client.list_files(s_path)
        if not s_files: continue

        logging.info(f"    👉 {s_name}")
        
        # 呼叫共用邏輯，傳入該季的所有檔案
        episodes = process_folder_videos(client, s_path, s_files)
        
        if episodes:
            json_str = json.dumps(episodes)
            season_data.append({'season': s_name, 'subs': json_str})
    
    if season_data:
        save_media('tv', drive_id, t_name, t_full_path, season_data)
        return True
    return False

# --- 主任務 ---
def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 開始全量掃描: {start_cloud_path}")

    drives = client.list_files(start_cloud_path)
    if not drives: return

    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])

    for drive in drive_list:
        drive_id = drive['name']
        drive_full_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"👉 Drive: {drive_id}")

        sub_folders = client.list_files(drive_full_path)
        if not sub_folders: continue
        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        
        if 'movies' in folder_map:
            m_path = posixpath.join(drive_full_path, folder_map['movies'])
            m_list = client.list_files(m_path)
            if m_list:
                for m in m_list:
                    if not m['is_dir']: continue
                    full = posixpath.join(m_path, m['name'])
                    if check_media_exists(full): continue
                    process_movie_item(client, drive_id, m['name'], full)

        if 'tv' in folder_map:
            t_path = posixpath.join(drive_full_path, folder_map['tv'])
            t_list = client.list_files(t_path)
            if t_list:
                for t in t_list:
                    if not t['is_dir']: continue
                    full = posixpath.join(t_path, t['name'])
                    if check_media_exists(full): continue
                    process_tv_item(client, drive_id, t['name'], full)

    logging.info("🏁 掃描結束！")

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return
    logging.info(f"🔄 [手動刷新] {row['name']}")
    
    if row['type'] == 'movie':
        process_movie_item(client, row['drive_id'], row['name'], row['full_path'])
    elif row['type'] == 'tv':
        process_tv_item(client, row['drive_id'], row['name'], row['full_path'])
    logging.info("✅ 刷新完成")
