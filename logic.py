import requests
import subprocess
import json
import os
import posixpath
import logging
import re
import urllib.parse
import tempfile
import time
from database import save_media, check_media_exists, get_media_by_id, delete_season_data

# 設定 Log
DATA_DIR = '/app/data'
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'), logging.StreamHandler()]
)

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.iso', '.ts')
SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub', '.smi', '.sup')
IMG_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.nfo', '.xml', '.txt')

class AlistClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {"Authorization": token, "Content-Type": "application/json"}

    def list_files(self, path, refresh=False):
        try:
            url = f"{self.url}/api/fs/list"
            body = {"path": path, "page": 1, "per_page": 0, "refresh": refresh}
            resp = requests.post(url, headers=self.headers, json=body)
            data = resp.json()
            if data and data.get('code') == 200: return data['data']['content']
        except: pass
        return []

    def get_raw_url(self, path):
        try:
            url = f"{self.url}/api/fs/get"
            resp = requests.post(url, headers=self.headers, json={"path": path})
            data = resp.json()
            if data and data.get('code') == 200: return data['data']['raw_url']
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
            return resp.json().get('code') == 200 
        except: return False

    def put_file(self, path, file_content):
        try:
            url = f"{self.url}/api/fs/put"
            encoded_path = urllib.parse.quote(path)
            put_headers = self.headers.copy()
            put_headers["File-Path"] = encoded_path
            resp = requests.put(url, headers=put_headers, data=file_content)
            return resp.json().get('code') == 200
        except: return False

    def remove_files(self, dir_path, file_names):
        try:
            url = f"{self.url}/api/fs/remove"
            body = {"dir": dir_path, "names": file_names}
            resp = requests.post(url, headers=self.headers, json=body)
            return resp.json().get('code') == 200
        except Exception as e:
            logging.error(f"Alist Remove Error: {e}")
            return False

class RcloneHandler:
    @staticmethod
    def check_remotes():
        try:
            cmd = "rclone listremotes"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, f"Error: {result.stderr}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def map_path(alist_path, root_mount="/Cloud"):
        if alist_path.startswith(root_mount):
            rel_path = alist_path[len(root_mount):].lstrip('/')
        else:
            rel_path = alist_path.lstrip('/')
            
        parts = rel_path.split('/', 1)
        if len(parts) < 2: return f"{parts[0]}:/"
        
        remote_name = parts[0]
        file_path = parts[1]
        
        if not file_path.startswith('/'):
            file_path = '/' + file_path
            
        return f"{remote_name}:{file_path}"

    @staticmethod
    def _sanitize_name(name):
        return name.replace('：', ':')

    @staticmethod
    def delete_file_single(rclone_path):
        if ':/' in rclone_path:
            remote_part, path_part = rclone_path.split(':/', 1)
            fixed_path_part = RcloneHandler._sanitize_name(path_part)
            final_path = f"{remote_part}:/{fixed_path_part}"
        else:
            final_path = RcloneHandler._sanitize_name(rclone_path)

        try:
            cmd = f'rclone delete "{final_path}" --retries 2'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0: return True, "Success"
            else: return False, result.stderr.strip()
        except Exception as e:
            return False, str(e)

    @staticmethod
    def delete_files_batch(rclone_folder_path, file_names):
        if ':/' in rclone_folder_path:
            remote, folder = rclone_folder_path.split(':/', 1)
            fixed_folder = RcloneHandler._sanitize_name(folder)
            final_folder_path = f"{remote}:/{fixed_folder}"
        else:
            final_folder_path = RcloneHandler._sanitize_name(rclone_folder_path)

        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', delete=False) as tf:
                for name in file_names:
                    fixed_name = RcloneHandler._sanitize_name(name)
                    tf.write(fixed_name + "\n")
                temp_file_path = tf.name
            
            cmd = f'rclone delete "{final_folder_path}" --files-from "{temp_file_path}" --retries 2'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0: return True, "Batch Success"
            else: return False, result.stderr.strip()
                
        except Exception as e:
            return False, str(e)
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    @staticmethod
    def purge_folder(rclone_folder_path):
        if ':/' in rclone_folder_path:
            remote, folder = rclone_folder_path.split(':/', 1)
            fixed_folder = RcloneHandler._sanitize_name(folder)
            final_path = f"{remote}:/{fixed_folder}"
        else:
            final_path = RcloneHandler._sanitize_name(rclone_folder_path)

        try:
            cmd = f'rclone purge "{final_path}" --retries 2'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0: return True, "Purge Success"
            else: return False, result.stderr.strip()
        except Exception as e:
            return False, str(e)

# --- 輔助函式 ---

def get_season_episode_key(filename):
    filename = filename.lower()
    match_std = re.search(r"s(\d{1,3})[\.\s]*e(\d{1,3})", filename)
    if match_std: return int(match_std.group(1)), int(match_std.group(2))
    match_chi = re.search(r"(?:第)?\s*(\d{1,3})\s*季.*?(?:第)?\s*(\d{1,3})\s*集", filename)
    if match_chi: return int(match_chi.group(1)), int(match_chi.group(2))
    return None

def get_season_only(filename):
    filename = filename.lower()
    match = re.search(r"s(\d{1,3})", filename)
    if match: return int(match.group(1))
    match_chi = re.search(r"(?:第)?\s*(\d{1,3})\s*季", filename)
    if match_chi: return int(match_chi.group(1))
    return None

def find_season_folder(client, base_path, season_num):
    items = client.list_files(base_path)
    if not items: return None
    for item in items:
        if not item['is_dir']: continue
        name = item['name']
        if "Season" not in name and "季" not in name: continue
        nums = re.findall(r"\d+", name)
        if nums and int(nums[0]) == season_num:
            return posixpath.join(base_path, name)
    return None

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
            if video_base in f['name']: return True, f['name']
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
            results.append({"name": ep_name, "status": "ok", "type": "external", "detail": f"[外部] {ext_name}"})
            continue 
        
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

# --- 字幕管理器邏輯 ---

def get_media_folders(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return {}
    folders = {}
    if row['type'] == 'movie':
        folders['Movie'] = row['full_path']
    else:
        items = client.list_files(row['full_path'])
        if items:
            items.sort(key=lambda x: x['name'])
            for item in items:
                if item['is_dir'] and ("Season" in item['name'] or "Specials" in item['name']):
                    folders[item['name']] = posixpath.join(row['full_path'], item['name'])
    return folders

def list_folder_files(alist_url, token, folder_path):
    client = AlistClient(alist_url, token)
    files = client.list_files(folder_path, refresh=True) 
    if not files: return []
    result = []
    for f in files:
        if f['is_dir']: continue
        fname = f['name']
        ext = os.path.splitext(fname)[1].lower()
        if ext in VIDEO_EXTS: ftype = "🎬 Video"
        elif ext in SUB_EXTS: ftype = "📝 Subtitle"
        elif ext in IMG_EXTS: ftype = "🖼️ Info/Img"
        else: ftype = "📄 Other"
        result.append({"name": fname, "type": ftype})
    def sort_key(item):
        t = item['type']
        if "Video" in t: return 0
        if "Subtitle" in t: return 1
        if "Info" in t: return 2
        return 3
    result.sort(key=lambda x: (sort_key(x), x['name']))
    return result

def execute_folder_rename(alist_url, token, folder_path):
    client = AlistClient(alist_url, token)
    logs = []
    logging.info(f"🔄 [Rename] 開始掃描目錄: {folder_path}")
    files = client.list_files(folder_path, refresh=True)
    if not files: return ["❌ 無法讀取目錄"]
    videos = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    subs = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    logging.info(f"   🔍 掃描結果: {len(videos)} 個影片, {len(subs)} 個字幕")
    if not videos: return ["⚠️ 此目錄無影片檔"]
    if not subs: return ["⚠️ 此目錄無字幕檔"]
    if len(videos) == 1 and len(subs) >= 1:
        vid = videos[0]; vid_base = os.path.splitext(vid['name'])[0]
        logging.info(f"   🎬 檢測為電影模式: {vid['name']}")
        for sub in subs:
            sub_ext = os.path.splitext(sub['name'])[1]
            target_name = f"{vid_base}{sub_ext}"
            if sub['name'] == target_name:
                logging.info(f"      ✅ 字幕已匹配: {sub['name']}")
                continue
            if any(f['name'] == target_name for f in files):
                logging.warning(f"      ⚠️ 目標檔名已存在，跳過: {target_name}")
                continue
            if client.rename(posixpath.join(folder_path, sub['name']), target_name):
                msg = f"✅ 改名成功: {sub['name']} -> {target_name}"
                logs.append(msg); logging.info(msg)
            else:
                msg = f"❌ 改名失敗: {sub['name']}"; logs.append(msg); logging.error(msg)
        return logs if logs else ["✅ 無需修改"]
    renamed_count = 0
    logging.info(f"   📺 檢測為劇集模式，開始集數匹配...")
    for vid in videos:
        vid_key = get_season_episode_key(vid['name'])
        if not vid_key: continue
        vid_base = os.path.splitext(vid['name'])[0]
        logging.info(f"      🎞️ 處理影片: S{vid_key[0]}E{vid_key[1]} ({vid['name']})")
        target_sub = None
        for sub in subs:
            sub_key = get_season_episode_key(sub['name'])
            if sub_key and sub_key == vid_key:
                target_sub = sub
                break
        if target_sub:
            sub_ext = os.path.splitext(target_sub['name'])[1]
            target_name = f"{vid_base}{sub_ext}"
            if target_sub['name'] == target_name: 
                logging.info("         ✅ 已正確命名")
                continue
            if any(f['name'] == target_name for f in files): 
                logging.info("         ⚠️ 目標已存在，跳過")
                continue
            if client.rename(posixpath.join(folder_path, target_sub['name']), target_name):
                msg = f"✅ S{vid_key[0]}E{vid_key[1]} 改名: {target_sub['name']} -> {target_name}"
                logs.append(msg); logging.info(msg); renamed_count += 1
            else:
                msg = f"❌ 改名失敗: {target_sub['name']}"; logs.append(msg); logging.error(msg)
        else:
            logging.info("         ⚠️ 無對應字幕")
    if renamed_count == 0 and not logs: return ["✅ 掃描完畢，無可修改項目"]
    return logs

def execute_folder_upload(alist_url, token, folder_path, files_dict):
    client = AlistClient(alist_url, token)
    logs = []; uploaded_count = 0
    for fname, content in files_dict.items():
        if not fname.lower().endswith(SUB_EXTS):
            msg = f"⚠️ 跳過 (非字幕): {fname}"; logs.append(msg); logging.warning(msg)
            continue
        full_path = posixpath.join(folder_path, fname)
        logging.info(f"⬆️ 上傳中: {fname} ...")
        if client.put_file(full_path, content):
            msg = f"✅ 上傳成功: {fname}"; logs.append(msg); logging.info(msg); uploaded_count += 1
        else:
            msg = f"❌ 上傳失敗: {fname}"; logs.append(msg); logging.error(msg)
    if uploaded_count == 0:
        logs.append("⚠️ 沒有有效字幕檔被上傳"); return logs
    logging.info("⏳ 等待 Alist 索引..."); time.sleep(1.5)
    logging.info("🔄 觸發自動改名..."); rename_logs = execute_folder_rename(alist_url, token, folder_path); logs.extend(rename_logs)
    return logs

def execute_file_deletion(alist_url, token, folder_path, file_names, alist_root="/Cloud"):
    client = AlistClient(alist_url, token); logs = []
    if not file_names: return ["⚠️ 未選擇檔案"]
    logging.info(f"🗑️ [Rclone] 準備刪除 {len(file_names)} 個檔案")
    rclone_folder_path = RcloneHandler.map_path(folder_path, alist_root)
    if not rclone_folder_path.endswith('/'): rclone_folder_path += '/'
    if len(file_names) == 1:
        name = file_names[0]
        full_file_path = f"{rclone_folder_path}{name}"
        success, err = RcloneHandler.delete_file_single(full_file_path)
        if success: logs.append(f"✅ 已刪除: {name}"); logging.info(f"✅ 已刪除: {name}")
        else: logs.append(f"❌ 刪除失敗: {name} ({err})"); logging.error(f"Single Delete Error: {err}")
    else:
        logging.info(f"   [Batch] 嘗試批次刪除...")
        batch_success, batch_err = RcloneHandler.delete_files_batch(rclone_folder_path, file_names)
        if batch_success: logs.append(f"✅ 批次刪除成功 ({len(file_names)} 檔)"); logging.info(f"✅ 批次刪除成功")
        else:
            logging.warning(f"   ⚠️ 批次失敗 ({batch_err})，降級為單檔迴圈刪除...")
            for name in file_names:
                full_file_path = f"{rclone_folder_path}{name}"
                success, err = RcloneHandler.delete_file_single(full_file_path)
                if success: logs.append(f"✅ 已刪除: {name}")
                else: logs.append(f"❌ 刪除失敗: {name}")
    logging.info("🔄 [Sync] 強制 Alist 重新整理目錄..."); client.list_files(folder_path, refresh=True)
    return logs

def execute_directory_purge(alist_url, token, folder_path, media_id, season_name, alist_root="/Cloud"):
    client = AlistClient(alist_url, token); logs = []
    logging.info(f"🧨 [Purge] 準備銷毀目錄: {folder_path}")
    rclone_folder_path = RcloneHandler.map_path(folder_path, alist_root)
    if not rclone_folder_path.endswith('/'): rclone_folder_path += '/'
    success, err = RcloneHandler.purge_folder(rclone_folder_path)
    if success:
        logs.append(f"✅ 目錄已銷毀: {folder_path}"); logging.info(f"✅ 目錄已銷毀")
        delete_season_data(media_id, season_name)
        parent = posixpath.dirname(folder_path)
        client.list_files(parent, refresh=True)
    else:
        logs.append(f"❌ 銷毀失敗: {err}"); logging.error(f"Purge Error: {err}")
    return logs

def import_subs_to_target(alist_url, token, source_folder, target_folder):
    client = AlistClient(alist_url, token)
    logging.info(f"📂 [匯入] 從 {source_folder} 到 {target_folder}")
    norm_src = source_folder.rstrip('/'); norm_target = target_folder.rstrip('/')
    src_files = client.list_files(source_folder)
    subs_to_copy = [f['name'] for f in src_files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    if not subs_to_copy: logging.warning("❌ 來源目錄沒有字幕檔"); return "無字幕", []
    if norm_src == norm_target:
        logging.info("   ℹ️ 來源與目標相同，跳過複製，直接執行修復")
    else:
        logging.info(f"   📋 準備複製 {len(subs_to_copy)} 個檔案...")
        if client.copy(source_folder, target_folder, subs_to_copy): logging.info(f"   ✅ 複製成功")
        else: logging.error(f"   ❌ 複製失敗"); return "複製失敗", []
    time.sleep(1); logging.info("🔄 執行改名對齊..."); execute_folder_rename(alist_url, token, target_folder)
    return "完成", []

# --- 舊接口 ---
def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 開始全量掃描: {start_cloud_path}")
    drives = client.list_files(start_cloud_path)
    if not drives: return
    drive_list = sorted([d for d in drives if d['is_dir']], key=lambda x: x['name'])
    for drive in drive_list:
        drive_id = drive['name']; drive_full_path = posixpath.join(start_cloud_path, drive_id)
        logging.info(f"👉 Drive: {drive_id}")
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
    logging.info("🏁 掃描結束！")

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return
    logging.info(f"🔄 [手動更新] 開始: {row['name']}")
    if row['type'] == 'movie': process_movie_item(client, row['drive_id'], row['name'], row['full_path'])
    elif row['type'] == 'tv': process_tv_item(client, row['drive_id'], row['name'], row['full_path'])
    logging.info(f"🏁 [手動更新] 完畢: {row['name']}")

def run_auto_fix(alist_url, token, media_id): pass
def import_subs_from_folder(alist_url, token, media_id, source_folder): pass
