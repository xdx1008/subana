import requests
import subprocess
import json
import os
import posixpath
import logging
import re # 新增 regex 模組

# 設定 Log
DATA_DIR = '/app/data'
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[FlushFileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv')
SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
REGEX_SEASON_EP = re.compile(r"(S\d{2}E\d{2})", re.IGNORECASE)

# --- 通用 API 類別 (讓兩個功能共用) ---
class AlistClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {"Authorization": token, "Content-Type": "application/json"}

    def api(self, endpoint, method="POST", body=None):
        try:
            url = f"{self.url}/api/fs/{endpoint}"
            if method == "POST":
                resp = requests.post(url, headers=self.headers, json=body)
            else:
                resp = requests.get(url, headers=self.headers, params=body)
            return resp.json()
        except Exception as e:
            logging.error(f"API 連線錯誤: {e}")
            return None

    def list_files(self, path):
        data = self.api("list", body={"path": path, "page": 1, "per_page": 0, "refresh": True})
        if data and data.get('code') == 200:
            return data['data']['content']
        return []

    def rename(self, full_path, new_name):
        # Alist Rename API: path 為完整路徑, name 為新檔名
        body = {"path": full_path, "name": new_name}
        data = self.api("rename", body=body)
        return data and data.get('code') == 200

    def put_text(self, path, content):
        url = f"{self.url}/api/fs/put"
        headers = self.headers.copy()
        headers["File-Path"] = requests.utils.quote(path)
        headers["Content-Type"] = "text/plain"
        try:
            resp = requests.put(url, headers=headers, data=content.encode('utf-8'))
            return resp.json().get('code') == 200
        except: return False
    
    def get_raw_url(self, path):
        data = self.api("get", body={"path": path})
        if data and data.get('code') == 200:
            return data['data']['raw_url']
        return None

# ================= Feature 1: 字幕分析 (Analyzer) =================
def run_analysis(alist_url, token, start_dir):
    logging.info("="*30)
    logging.info(f"🚀 [分析任務] 啟動，掃描: {start_dir}")
    client = AlistClient(alist_url, token)

    def analyze_video(file_url):
        cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-select_streams", "s", file_url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0: return ["❌ 格式錯誤"]
            if not result.stdout: return None
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
        except subprocess.TimeoutExpired: return ["⏱️ 超時"]
        except Exception as e: return [f"❌ {str(e)}"]

    def process_folder(current_path):
        logging.info(f"📂 掃描: {current_path}")
        items = client.list_files(current_path)
        if not items: return

        sub_folders = [i for i in items if i['is_dir']]
        videos = [i for i in items if not i['is_dir'] and i['name'].lower().endswith(VIDEO_EXTS)]

        for folder in sub_folders:
            process_folder(posixpath.join(current_path, folder['name']))

        if videos:
            logging.info(f"🎬 發現 {len(videos)} 部影片，分析中...")
            report_lines = [f"📁 目錄: {current_path}", "=" * 60]
            
            for vid in videos:
                full_path = posixpath.join(current_path, vid['name'])
                raw_url = client.get_raw_url(full_path)
                
                if raw_url:
                    subs = analyze_video(raw_url)
                    sub_info = ", ".join(subs) if subs else "🈚 無內嵌字幕"
                    if subs: logging.info(f"   ✅ {vid['name']}")
                    else: logging.info(f"   🈚 {vid['name']}")
                else:
                    sub_info = "❌ 無法取得連結"
                    logging.warning(f"   ❌ {vid['name']}")
                
                report_lines.append(f"{vid['name']:<40} | {sub_info}")
            
            parent_dir = posixpath.dirname(current_path)
            folder_name = posixpath.basename(current_path) or "Root"
            report_path = posixpath.join(parent_dir, f"{folder_name}_MediaInfo.txt")
            
            if client.put_text(report_path, "\n".join(report_lines)):
                logging.info(f"📤 報告已存: {report_path}")
            else:
                logging.error(f"❌ 報告存檔失敗")
            logging.info("-" * 30)

    try:
        process_folder(start_dir)
        logging.info("🏁 [分析任務] 結束")
    except Exception as e:
        logging.critical(f"分析執行錯誤: {e}")

# ================= Feature 2: 字幕對齊 (Renamer) =================
def run_renamer(alist_url, token, video_dir, sub_dir, dry_run=True):
    logging.info("="*30)
    mode_str = "🔍 預覽 (Dry Run)" if dry_run else "⚡ 正式執行 (Execute)"
    logging.info(f"🚀 [字幕對齊] {mode_str}")
    logging.info(f"   影片目錄: {video_dir}")
    logging.info(f"   字幕目錄: {sub_dir}")

    client = AlistClient(alist_url, token)

    try:
        # 1. 取得列表
        videos = client.list_files(video_dir)
        subs = client.list_files(sub_dir)
        
        # 過濾
        valid_videos = [v for v in videos if not v['is_dir'] and v['name'].lower().endswith(VIDEO_EXTS)]
        valid_subs = [s for s in subs if not s['is_dir'] and s['name'].lower().endswith(SUB_EXTS)]

        logging.info(f"   找到影片: {len(valid_videos)} / 字幕: {len(valid_subs)}")

        if not valid_videos or not valid_subs:
            logging.warning("⚠️ 找不到足夠的檔案，任務中止")
            return

        # 2. 建立影片索引 Map { "S01E01": "VideoName_NoExt" }
        video_map = {}
        for v in valid_videos:
            match = REGEX_SEASON_EP.search(v['name'])
            if match:
                key = match.group(1).upper()
                name_no_ext = os.path.splitext(v['name'])[0]
                video_map[key] = name_no_ext

        # 3. 比對與改名
        match_count = 0
        for s in valid_subs:
            match = REGEX_SEASON_EP.search(s['name'])
            if match:
                key = match.group(1).upper()
                if key in video_map:
                    video_name = video_map[key]
                    sub_ext = os.path.splitext(s['name'])[1]
                    new_name = f"{video_name}{sub_ext}"

                    if s['name'] != new_name:
                        match_count += 1
                        msg = f"[{key}] {s['name']} -> {new_name}"
                        
                        if dry_run:
                            logging.info(f"🔍 [預覽] {msg}")
                        else:
                            full_path = posixpath.join(sub_dir, s['name'])
                            if client.rename(full_path, new_name):
                                logging.info(f"✅ [成功] {msg}")
                            else:
                                logging.error(f"❌ [失敗] {msg}")
        
        if match_count == 0:
            logging.info("✨ 所有字幕皆已對齊，無需修改。")
        else:
            logging.info(f"🏁 處理完成，共 {'預覽' if dry_run else '修改'} {match_count} 個檔案")

    except Exception as e:
        logging.critical(f"對齊執行錯誤: {e}")
