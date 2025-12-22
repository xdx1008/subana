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
        try:
            url = f"{self.url}/api/fs/rename"
            body = {"path": path, "name": new_name}
            resp = requests.post(url, headers=self.headers, json=body)
            return resp.json().get('code') == 200
        except: return False

    def copy(self, src_dir, dst_dir, file_names):
        try:
            url = f"{self.url}/api/fs/copy"
            body = {"src_dir": src_dir, "dst_dir": dst_dir, "names": file_names}
            resp = requests.post(url, headers=self.headers, json=body)
            data = resp.json()
            return data.get('code') == 200 
        except Exception as e:
            logging.error(f"Copy Error: {e}")
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

# --- 字幕修復與匯入 ---

def fix_subtitle_names(client, folder_path):
    logs = []
    files = client.list_files(folder_path)
    if not files: return 0, ["無法讀取目錄"]

    videos = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    subs = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    
    renamed_count = 0

    # 1. 電影模式
    if len(videos) == 1 and len(subs) == 1:
        vid = videos[0]; sub = subs[0]
        vid_base = os.path.splitext(vid['name'])[0]
        sub_ext = os.path.splitext(sub['name'])[1]
        
        if vid_base not in sub['name']:
            new_name = f"{vid_base}{sub_ext}"
            full_path = posixpath.join(folder_path, sub['name'])
            if client.rename(full_path, new_name):
                logs.append(f"✅ 改名: {sub['name']} -> {new_name}")
                renamed_count += 1
            else: logs.append(f"❌ 改名失敗: {sub['name']}")
        return renamed_count, logs

    # 2. 劇集模式
    for vid in videos:
        match = REGEX_SEASON_EP.search(vid['name'])
        if not match: continue
        
        season_ep_key = match.group(0).upper()
        vid_base = os.path.splitext(vid['name'])[0]

        target_sub = None
        for sub in subs:
            if season_ep_key in sub['name'].upper():
                target_sub = sub
                break
        
        if target_sub:
            if vid_base in target_sub['name']: continue
            sub_ext = os.path.splitext(target_sub['name'])[1]
            new_name = f"{vid_base}{sub_ext}"
            
            if any(f['name'] == new_name for f in files): continue

            full_path = posixpath.join(folder_path, target_sub['name'])
            if client.rename(full_path, new_name):
                logs.append(f"✅ 改名: {target_sub['name']} -> {new_name}")
                renamed_count += 1
            else: logs.append(f"❌ 改名失敗: {target_sub['name']}")

    return renamed_count, logs

def import_subs_from_folder(alist_url, token, media_id, source_folder):
    """
    跨目錄匯入邏輯 (含同目錄防呆)
    """
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return "找不到媒體"

    logging.info(f"📂 [匯入] 從 {source_folder} 到 {row['name']}")
    
    # 正規化來源路徑 (去除結尾斜線，避免比對錯誤)
    norm_src = source_folder.rstrip('/')

    # 1. 取得來源字幕
    src_files = client.list_files(source_folder)
    subs_to_copy = [f['name'] for f in src_files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    
    if not subs_to_copy:
        return "❌ 來源目錄沒有字幕檔"

    # 2. 決定目標目錄
    targets = []
    if row['type'] == 'movie':
        targets.append(row['full_path'])
    else:
        sub_items = client.list_files(row['full_path'])
        for item in sub_items:
            if item['is_dir'] and ("Season" in item['name'] or "Specials" in item['name']):
                targets.append(posixpath.join(row['full_path'], item['name']))
    
    if not targets:
        return "❌ 找不到目標資料夾"

    copied_count = 0
    renamed_total = 0
    
    # 3. 處理每個目標資料夾
    for target_dir in targets:
        norm_target = target_dir.rstrip('/')
        
        # 🔥 防呆機制：如果是同一個目錄，跳過複製，直接修復
        if norm_src == norm_target:
            logging.info(f"   ℹ️ 來源與目標相同，跳過複製，直接執行改名修復: {target_dir}")
            count, logs = fix_subtitle_names(client, target_dir)
            renamed_total += count
            for l in logs: logging.info(l)
            continue

        # 不同目錄 -> 執行複製 + 修復
        logging.info(f"   📋 複製字幕到: {target_dir}")
        if client.copy(source_folder, target_dir, subs_to_copy):
            copied_count += len(subs_to_copy)
            count, logs = fix_subtitle_names(client, target_dir)
            renamed_total += count
            for l in logs: logging.info(l)
        else:
            logging.error(f"   ❌ 複製失敗: {target_dir}")

    # 4. 更新資料庫
    run_single_refresh(alist_url, token, media_id)
    
    result_msg = ""
    if copied_count > 0:
        result_msg += f"已複製 {copied_count} 個檔案。"
    if renamed_total > 0:
        result_msg += f" 已修復 {renamed_total} 個檔名。"
    if not result_msg:
        result_msg = "操作完成 (無變更)"
        
    return result_msg

# --- 任務接口 ---
def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    drives = client.list_files(start_cloud_path)
    if not drives: return
    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])
    for drive in drive_list:
        drive_id = drive['name']; drive_full_path = posixpath.join(start_cloud_path, drive_id)
        sub_folders = client.list_files(drive_full_path)
        if not sub_folders: continue
        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        if 'movies' in folder_map:
            m_path = posixpath.join(drive_full_path, folder_map['movies']); m_list = client.list_files(m_path)
            if m_list:
                for m in m_list:
                    if not m['is_dir']: continue
                    full = posixpath.join(m_path, m['name'])
                    if check_media_exists(full): continue
                    process_movie_item(client, drive_id, m['name'], full)
        if 'tv' in folder_map:
            t_path = posixpath.join(drive_full_path, folder_map['tv']); t_list = client.list_files(t_path)
            if t_list:
                for t in t_list:
                    if not t['is_dir']: continue
                    full = posixpath.join(t_path, t['name'])
                    if check_media_exists(full): continue
                    process_tv_item(client, drive_id, t['name'], full)

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return
    if row['type'] == 'movie': process_movie_item(client, row['drive_id'], row['name'], row['full_path'])
    elif row['type'] == 'tv': process_tv_item(client, row['drive_id'], row['name'], row['full_path'])

def run_auto_fix(alist_url, token, media_id):
    """(原地修復接口) - 呼叫 import_subs_from_folder 但來源=目標"""
    row = get_media_by_id(media_id)
    if not row: return "No Data"
    # 直接使用我們剛改寫的 import 函式，傳入自身路徑，就會觸發防呆機制
    # 注意：若是劇集，row['full_path'] 是劇集根目錄，import 函式會自動處理 Season 子目錄
    return import_subs_from_folder(alist_url, token, media_id, row['full_path'])
