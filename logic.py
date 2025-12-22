import requests
import subprocess
import json
import os
import posixpath
import logging
import re
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
SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
# 正則表達式：匹配 S01E01 或 s1e1
REGEX_SEASON_EP = re.compile(r"[sS](\d{1,3})[eE](\d{1,3})")

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

    def rename(self, path, new_name):
        """Alist Rename API"""
        try:
            url = f"{self.url}/api/fs/rename"
            body = {"path": path, "name": new_name}
            resp = requests.post(url, headers=self.headers, json=body)
            data = resp.json()
            return data.get('code') == 200
        except Exception as e:
            logging.error(f"Rename Error: {e}")
            return False

def has_chinese_embedded(file_url):
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0: return False, "Format Error"
        
        info = json.loads(result.stdout)
        streams = info.get('streams', [])
        keywords = ['chi', 'zho', 'chinese', 'cht', 'chs', '繁體', '简体', 'mandarin', 'zh-tw', 'zh-cn']
        
        track_info = []
        has_chi = False
        for i, s in enumerate(streams):
            tags = s.get('tags', {})
            lang = tags.get('language', 'und').lower()
            title = tags.get('title', '').lower()
            codec = s.get('codec_name', 'unknown')
            if any(k in lang for k in keywords) or any(k in title for k in keywords): has_chi = True
            track_info.append(f"{lang}({codec})")
            
        return has_chi, ", ".join(track_info)
    except: return False, "Analyze Timeout"

def check_external_sub(video_name, all_files):
    video_base = os.path.splitext(video_name)[0]
    for f in all_files:
        if f['is_dir']: continue
        if f['name'].lower().endswith(SUB_EXTS):
            if video_base in f['name']:
                return True, f['name']
    return False, None

# --- 核心邏輯 ---

def process_folder_videos(client, full_path, all_files):
    results = []
    video_files = [f for f in all_files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    video_files.sort(key=lambda x: x['name'])

    for vid in video_files:
        ep_name = vid['name']
        logging.info(f"      Checking: {ep_name} ...")
        
        # 1. 外部字幕
        has_ext, ext_name = check_external_sub(ep_name, all_files)
        
        if has_ext:
            logging.info(f"         ✅ 找到外部字幕: {ext_name}")
            results.append({
                "name": ep_name,
                "status": "ok",
                "type": "external",
                "detail": f"[外部] {ext_name}"
            })
            continue 
        
        # 2. 內嵌字幕
        logging.info(f"         ⚠️ 無外部字幕，檢查內嵌...")
        raw_url = client.get_raw_url(posixpath.join(full_path, ep_name))
        
        if raw_url:
            has_emb, track_info = has_chinese_embedded(raw_url)
            if has_emb:
                results.append({"name": ep_name, "status": "ok", "type": "embedded", "detail": f"[內嵌] {track_info}"})
            else:
                results.append({"name": ep_name, "status": "missing", "detail": track_info if track_info else "No subs found"})
        else:
            results.append({"name": ep_name, "status": "error", "detail": "Link Error"})
                
    return results

def process_movie_item(client, drive_id, m_name, m_full_path):
    logging.info(f"   🎥 分析電影: {m_name}")
    files = client.list_files(m_full_path)
    if not files: return False
    episodes = process_folder_videos(client, m_full_path, files)
    if episodes:
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': json.dumps(episodes)}])
        return True
    return False

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
        episodes = process_folder_videos(client, s_path, s_files)
        if episodes:
            season_data.append({'season': s_name, 'subs': json.dumps(episodes)})
    
    if season_data:
        save_media('tv', drive_id, t_name, t_full_path, season_data)
        return True
    return False

# --- 🔥 新增：字幕修復邏輯 ---
def fix_subtitle_names(client, folder_path):
    """
    自動對齊字幕檔名
    回傳: (success_count, logs list)
    """
    logs = []
    files = client.list_files(folder_path)
    if not files: return 0, ["無法讀取目錄"]

    videos = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    subs = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    
    renamed_count = 0

    # 1. 電影模式：1個影片 + 1個字幕
    if len(videos) == 1 and len(subs) == 1:
        vid = videos[0]
        sub = subs[0]
        vid_base = os.path.splitext(vid['name'])[0]
        sub_ext = os.path.splitext(sub['name'])[1]
        
        # 如果字幕檔名不包含影片檔名，則改名
        if vid_base not in sub['name']:
            new_name = f"{vid_base}{sub_ext}" # 直接改成 Video.srt
            full_path = posixpath.join(folder_path, sub['name'])
            if client.rename(full_path, new_name):
                logs.append(f"✅ 修復: {sub['name']} -> {new_name}")
                renamed_count += 1
            else:
                logs.append(f"❌ 失敗: {sub['name']}")
        return renamed_count, logs

    # 2. 劇集模式：SxxExx 匹配
    for vid in videos:
        # 提取影片 S01E01
        match = REGEX_SEASON_EP.search(vid['name'])
        if not match: continue
        
        season_ep_key = match.group(0).upper() # S01E01
        vid_base = os.path.splitext(vid['name'])[0]

        # 在字幕中尋找同樣包含 S01E01 的檔案
        target_sub = None
        for sub in subs:
            if season_ep_key in sub['name'].upper():
                target_sub = sub
                break
        
        if target_sub:
            # 如果已經對齊了，跳過
            if vid_base in target_sub['name']: continue
            
            # 準備改名
            sub_ext = os.path.splitext(target_sub['name'])[1]
            new_name = f"{vid_base}{sub_ext}" # VideoName.srt
            
            # 檢查新檔名是否已存在 (避免覆蓋)
            if any(f['name'] == new_name for f in files):
                continue

            full_path = posixpath.join(folder_path, target_sub['name'])
            if client.rename(full_path, new_name):
                logs.append(f"✅ 對齊: {target_sub['name']} -> {new_name}")
                renamed_count += 1
            else:
                logs.append(f"❌ 失敗: {target_sub['name']}")

    return renamed_count, logs

# --- 任務接口 ---
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

def run_auto_fix(alist_url, token, media_id):
    """執行自動修復並重掃"""
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return "找不到資料"
    
    total_renamed = 0
    all_logs = []

    logging.info(f"🛠️ [字幕修復] 開始: {row['name']}")

    if row['type'] == 'movie':
        count, logs = fix_subtitle_names(client, row['full_path'])
        total_renamed += count
        all_logs.extend(logs)
    elif row['type'] == 'tv':
        # 劇集需要進入每一季的資料夾
        seasons = client.list_files(row['full_path'])
        for s in seasons:
            if not s['is_dir']: continue
            if "Season" not in s['name'] and "Specials" not in s['name']: continue
            
            s_path = posixpath.join(row['full_path'], s['name'])
            count, logs = fix_subtitle_names(client, s_path)
            total_renamed += count
            all_logs.extend(logs)

    # 如果有變動，立即重掃資料庫
    if total_renamed > 0:
        logging.info("📝 偵測到檔名變更，立即更新資料庫...")
        run_single_refresh(alist_url, token, media_id)
    
    result_msg = f"共修復 {total_renamed} 個檔案"
    if all_logs:
        for l in all_logs: logging.info(l)
        
    return result_msg
