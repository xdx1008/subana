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
from collections import Counter
from database import save_media, get_media_by_id, delete_season_data, get_media_by_path, get_all_media, get_db_connection

# 設定 Log
DATA_DIR = '/app/data'
LOG_FILE = os.path.join(DATA_DIR, 'app.log')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

if not logging.getLogger().hasHandlers():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(message)s',
        datefmt='%H:%M:%S',
        handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'), logging.StreamHandler()]
    )

VIDEO_EXTS = ('.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.iso', '.ts', '.m2ts')
SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub', '.smi', '.sup')
IMG_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.nfo', '.xml', '.txt')
CHI_KEYWORDS = ['chi', 'zho', 'chinese', 'zh', 'cht', 'chs', 'cmn', 'yue']

class AlistClient:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {"Authorization": token, "Content-Type": "application/json"}

    def _request(self, method, endpoint, json_data=None, **kwargs):
        try:
            url = f"{self.url}/api/fs/{endpoint}"
            resp = requests.request(method, url, headers=self.headers, json=json_data, **kwargs)
            return resp.json()
        except: return None

    def list_files(self, path, refresh=False):
        # [MODIFIED] Return None on failure to distinguish from empty folder
        data = self._request('post', 'list', {"path": path, "page": 1, "per_page": 0, "refresh": refresh})
        if data and data.get('code') == 200: 
            content = data['data']['content']
            return content if content is not None else []
        return None

    def get_raw_url(self, path):
        data = self._request('post', 'get', {"path": path})
        if data and data.get('code') == 200: return data['data']['raw_url']
        return None

    def rename(self, path, new_name):
        data = self._request('post', 'rename', {"path": path, "name": new_name})
        return data and data.get('code') == 200

    def copy(self, src_dir, dst_dir, file_names):
        data = self._request('post', 'copy', {"src_dir": src_dir, "dst_dir": dst_dir, "names": file_names})
        return data and data.get('code') == 200 

    def put_file(self, path, file_content):
        try:
            url = f"{self.url}/api/fs/put"
            headers = self.headers.copy()
            headers["File-Path"] = urllib.parse.quote(path)
            resp = requests.put(url, headers=headers, data=file_content)
            return resp.json().get('code') == 200
        except: return False

    def remove_files(self, dir_path, file_names):
        data = self._request('post', 'remove', {"dir": dir_path, "names": file_names})
        return data and data.get('code') == 200

class RcloneHandler:
    _current_process = None

    @staticmethod
    def _get_conf_path():
        conf_path = "/root/.config/rclone/rclone.conf"
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    if data.get("rclone_conf"):
                        conf_path = data.get("rclone_conf")
        except: pass
        return conf_path

    @staticmethod
    def _get_base_cmd_str():
        conf = RcloneHandler._get_conf_path()
        if conf:
            return f'rclone --config "{conf}"'
        return "rclone"

    @staticmethod
    def _run_cmd(cmd_str):
        logging.info(f"   🔧 [EXEC] {cmd_str}") 
        try:
            result = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            if result.returncode != 0:
                logging.error(f"   ❌ [STDERR] {result.stderr.strip()}")
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except Exception as e: return False, "", str(e)

    @staticmethod
    def check_remotes():
        ok, out, err = RcloneHandler._run_cmd(f"{RcloneHandler._get_base_cmd_str()} listremotes")
        return ok, out if ok else err

    @staticmethod
    def map_path(alist_path, root_mount="/Cloud"):
        rel = alist_path[len(root_mount):].lstrip('/') if alist_path.startswith(root_mount) else alist_path.lstrip('/')
        parts = rel.split('/', 1)
        if len(parts) < 2: return f"{parts[0]}:/"
        path_part = '/' + parts[1] if not parts[1].startswith('/') else parts[1]
        return f"{parts[0]}:{path_part}"

    @staticmethod
    def _sanitize_name(name): return name.replace('：', ':')

    @staticmethod
    def delete_file_single(rclone_path):
        final_path = rclone_path
        if ':/' in rclone_path:
            remote, path = rclone_path.split(':/', 1)
            final_path = f"{remote}:/{RcloneHandler._sanitize_name(path)}"
        else:
            final_path = RcloneHandler._sanitize_name(rclone_path)
            
        cmd = f'{RcloneHandler._get_base_cmd_str()} delete "{final_path}" --retries 2'
        ok, _, err = RcloneHandler._run_cmd(cmd)
        return ok, err

    @staticmethod
    def delete_files_batch(rclone_folder_path, file_names):
        final_folder = rclone_folder_path
        if ':/' in rclone_folder_path:
            remote, folder = rclone_folder_path.split(':/', 1)
            final_folder = f"{remote}:/{RcloneHandler._sanitize_name(folder)}"
        
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', delete=False) as tf:
                tf.write("\n".join([RcloneHandler._sanitize_name(n) for n in file_names]))
                temp_file = tf.name
            cmd = f'{RcloneHandler._get_base_cmd_str()} delete "{final_folder}" --files-from "{temp_file}" --retries 2'
            ok, _, err = RcloneHandler._run_cmd(cmd)
            return ok, err
        finally:
            if temp_file and os.path.exists(temp_file): os.remove(temp_file)

    @staticmethod
    def purge_folder(rclone_folder_path):
        final_path = rclone_folder_path
        if ':/' in rclone_folder_path:
            remote, folder = rclone_folder_path.split(':/', 1)
            final_path = f"{remote}:/{RcloneHandler._sanitize_name(folder)}"
        
        cmd = f'{RcloneHandler._get_base_cmd_str()} purge "{final_path}" --retries 2'
        ok, _, err = RcloneHandler._run_cmd(cmd)
        return ok, err

    @staticmethod
    def get_link(rclone_path):
        final_path = rclone_path
        if ':/' in rclone_path:
            remote, folder = rclone_path.split(':/', 1)
            final_path = f"{remote}:/{RcloneHandler._sanitize_name(folder)}"
            
        cmd = f'{RcloneHandler._get_base_cmd_str()} link "{final_path}"'
        ok, out, err = RcloneHandler._run_cmd(cmd)
        if ok: return out
        logging.error(f"      -> Link Failed: {err}")
        return None

    @classmethod
    def kill_sync_process(cls):
        if cls._current_process:
            try:
                cls._current_process.terminate()
                return True
            except Exception as e:
                print(f"Error killing process: {e}")
        return False

    @classmethod
    def get_remote_free_space(cls, remote_path):
        base_cmd = ["rclone"]
        conf_path = cls._get_conf_path()
        if conf_path: base_cmd.extend(["--config", conf_path])
        
        cmd = base_cmd + ["about", remote_path]
        logging.info(f"   ☁️ [CMD] {' '.join(cmd)}")
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            free = "N/A"
            total = "N/A"
            
            if res.returncode == 0:
                m_free = re.search(r'Free:\s+(.+)', res.stdout, re.IGNORECASE)
                if m_free: free = m_free.group(1).strip()
                
                m_total = re.search(r'Total:\s+(.+)', res.stdout, re.IGNORECASE)
                if m_total: total = m_total.group(1).strip()
            else:
                logging.error(f"   ❌ [Rclone Output] {res.stderr.strip() or res.stdout.strip()}")
                
            return free, total
        except Exception as e:
            logging.error(f"   ❌ [CMD Exception] {str(e)}")
            return "Err", "Err"

    @classmethod
    def run_sync_process(cls, local_root, remote_root, bandwidth, min_age="1m", transfers="4"):
        base_cmd_list = ["rclone"]
        conf_path = cls._get_conf_path()
        if conf_path:
            base_cmd_list.extend(["--config", conf_path])

        yield f"🚀 Starting Sync (BW: {bandwidth}, Threads: {transfers})\n"
        yield f"   📂 Local: {local_root} -> Remote: {remote_root}\n"
        if conf_path: yield f"   📋 Config: {conf_path}\n"
        
        cmd = base_cmd_list + [
            "copy", local_root, remote_root,
            "--ignore-existing",
            "--exclude", ".DS_Store",
            "--exclude", "._*",
            "--filter", "+ /tv/**",
            "--filter", "+ /movies/**",
            "--filter", "- **", 
            "--bwlimit", bandwidth,
            "--min-age", min_age,
            "--transfers", str(transfers),
            "--stats-file-name-length", "0",
            "-v", "--stats", "2s" 
        ]
        
        logging.info(f"   🔄 [Sync CMD] {' '.join(cmd)}")

        try:
            cls._current_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True
            )
            
            for line in cls._current_process.stdout:
                yield line
            
            cls._current_process.wait()
            rc = cls._current_process.returncode
            cls._current_process = None

            if rc == 0:
                yield f"✅ Sync Finished.\n"
            elif rc == -15 or rc == 143:
                yield f"⚠️ Sync Interrupted.\n"
                return 
            else:
                yield f"❌ Sync Failed (RC={rc}).\n"
        except Exception as e:
            yield f"❌ Error executing rclone: {str(e)}\n"
            cls._current_process = None

        yield f"========================================\n"
        yield f"🏁 Task Completed.\n"

class MediaInfoParser:
    @staticmethod
    def _format_bitrate(bps, tags=None):
        val = None
        if bps and bps.isdigit(): val = int(bps)
        elif tags:
            for k in ['BPS', 'BPS-eng', 'bps']:
                if k in tags and tags[k].isdigit(): val = int(tags[k]); break
        return f"{val/1_000_000:.1f} Mb/s" if val else "N/A"

    @staticmethod
    def _format_time(seconds):
        if not seconds: return None
        try:
            if ":" in str(seconds):
                parts = str(seconds).split(':')
                return f"{int(float(parts[0])):02d}:{int(float(parts[1])):02d}:{int(float(parts[2])):02d}"
            sec = float(seconds)
            m, s = divmod(sec, 60)
            h, m = divmod(m, 60)
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"
        except: return None

    @staticmethod
    def _get_audio_codec_display(codec_name, profile, tags=None):
        c = codec_name.lower(); p = str(profile).lower() if profile else ""
        t = str(tags).lower() if tags else ""
        if 'truehd' in c: return "TrueHD Atmos" if ("atmos" in p or "atmos" in t) else "TrueHD"
        if 'eac3' in c:   return "DDP Atmos" if ("atmos" in p or "atmos" in t) else "Dolby Digital Plus"
        if 'ac3' in c:    return "Dolby Digital"
        if 'dts' in c:
            if 'x' in p or 'x' in c or 'x' in t: return "DTS:X"
            if 'ma' in p or 'ma' in t: return "DTS-HD MA"
            if 'hra' in p: return "DTS-HD HRA"
            return "DTS"
        if 'flac' in c: return "FLAC"
        if 'opus' in c: return "Opus"
        if 'aac' in c: return "AAC"
        return c.upper()

    @staticmethod
    def _get_video_codec_display(codec_name, profile):
        c = codec_name.lower()
        if 'hevc' in c: return "HEVC"
        if 'h264' in c: return "AVC"
        if 'av1' in c: return "AV1"
        if 'vp9' in c: return "VP9"
        return c.upper()

    @staticmethod
    def _get_video_dynamic_range(stream_info):
        color = stream_info.get('color_transfer', '')
        sides = stream_info.get('side_data_list', [])
        is_hdr = False; dr_type = []
        if color in ['smpte2084', 'arib-std-b67']:
            is_hdr = True
            if color == 'smpte2084': dr_type.append("HDR10")
            elif color == 'arib-std-b67': dr_type.append("HLG")
        for side in sides:
            stype = side.get('side_data_type', '')
            if 'DOVI' in stype: is_hdr = True; dr_type.append("Dolby Vision")
        final_dr = "HDR" if is_hdr else "SDR"
        unique_types = sorted(list(set(dr_type)))
        final_type_str = " / ".join(unique_types) if unique_types else ("SDR" if not is_hdr else "HDR10")
        return final_dr, final_type_str

    @staticmethod
    def analyze_media(file_url):
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0: return {"error": "FFprobe Failed"}
            data = json.loads(result.stdout)
            fmt = data.get('format', {})
            streams = data.get('streams', [])
            info = {}
            
            duration = MediaInfoParser._format_time(fmt.get('duration'))
            if not duration:
                vid_stream = next((s for s in streams if s['codec_type'] == 'video'), {})
                duration = MediaInfoParser._format_time(vid_stream.get('tags', {}).get('DURATION'))
            info['Duration'] = duration if duration else "N/A"
            info['Total Bitrate'] = MediaInfoParser._format_bitrate(fmt.get('bit_rate'), fmt.get('tags'))
            info['Size'] = f"{int(fmt.get('size', 0))/1024/1024/1024:.2f} GB" if fmt.get('size') else "N/A"

            vid = next((s for s in streams if s['codec_type'] == 'video'), None)
            if vid:
                info['Video Codec'] = MediaInfoParser._get_video_codec_display(vid.get('codec_name', ''), vid.get('profile'))
                info['Resolution'] = f"{vid.get('width')}x{vid.get('height')}"
                try:
                    num, den = map(int, vid.get('r_frame_rate', '0/0').split('/'))
                    info['Frame Rate'] = f"{num/den:.2f} fps" if den > 0 else "N/A"
                except: info['Frame Rate'] = "N/A"
                
                pix = vid.get('pix_fmt', '')
                info['Bit Depth'] = "10-bit" if '10' in pix else ("12-bit" if '12' in pix else "8-bit")
                dr, dr_t = MediaInfoParser._get_video_dynamic_range(vid)
                info['Video Dynamic Range'] = dr

            auds = [s for s in streams if s['codec_type'] == 'audio']
            if auds:
                main_a = next((s for s in auds if s.get('disposition', {}).get('default') == 1), auds[0])
                info['Audio Codec'] = MediaInfoParser._get_audio_codec_display(main_a.get('codec_name', ''), main_a.get('profile'), main_a.get('tags'))
                ch = main_a.get('channels', 0)
                info['Audio Channels'] = '5.1' if ch==6 else ('7.1' if ch==8 else str(ch))

            subs = [s for s in streams if s['codec_type'] == 'subtitle']
            info['Subtitle Stream Count'] = len(subs)
            sub_langs = list(set([s.get('tags', {}).get('language', 'und') for s in subs]))
            info['Subtitle Languages'] = "/".join(sub_langs) if sub_langs else "und"
            
            return info
        except Exception as e: return {"error": str(e)}

# --- Helpers ---
def get_season_episode_key(filename):
    f = filename.lower()
    m = re.search(r"s(\d{1,3})[\.\s]*e(\d{1,3})", f)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r"(?:第)?\s*(\d{1,3})\s*季.*?(?:第)?\s*(\d{1,3})\s*集", f)
    if m: return int(m.group(1)), int(m.group(2))
    return None

def check_external_sub(video_name, all_files):
    base = os.path.splitext(video_name)[0]
    for f in all_files:
        if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS):
            if base in f['name']: return True, f['name']
    return False, None

def get_detailed_media_info(file_path, alist_root="/Cloud"):
    rclone_path = RcloneHandler.map_path(file_path, alist_root)
    file_url = RcloneHandler.get_link(rclone_path)
    if not file_url: return {"error": "Rclone Link Failed"}
    return MediaInfoParser.analyze_media(file_url)

def _determine_video_status(ep_name, all_files, full_path, root_path, cached_info=None):
    logging.info("-" * 50)
    logging.info(f"🎞️ [FILE] {ep_name}")
    
    media_info = {}
    use_cache = False
    if cached_info and "error" not in cached_info:
        if cached_info.get("Duration") or cached_info.get("Run Time"):
            use_cache = True
            
    if use_cache:
        logging.info(f"   ⚡ [CACHE] Skipping FFprobe (Using existing data)")
        media_info = cached_info
    else:
        logging.info(f"   🚀 [INFO] Starting Analysis (No cache or force refresh)...")
        media_info = get_detailed_media_info(posixpath.join(full_path, ep_name), root_path)
    
    has_ext, ext_name = check_external_sub(ep_name, all_files)
    if has_ext: logging.info(f"   ✅ [EXT] Found: {ext_name}")
    else: logging.info(f"   ❌ [EXT] None")

    has_emb_chi = False
    emb_detail = ""
    if "error" not in media_info:
        sub_cnt = media_info.get('Subtitle Stream Count', 0)
        sub_langs = media_info.get('Subtitle Languages', '').lower()
        if not use_cache: logging.info(f"   🔍 [EMB] Found {sub_cnt} tracks: {media_info.get('Subtitle Languages')}")
        if sub_cnt > 0:
            if any(k in sub_langs for k in CHI_KEYWORDS):
                has_emb_chi = True
                emb_detail = f"[內嵌] {sub_cnt} tracks ({media_info.get('Subtitle Languages')})"
                if not use_cache: logging.info("   ✅ [EMB] Chinese detected!")
            else:
                emb_detail = f"No Chinese subs (Found: {media_info.get('Subtitle Languages')})"
                if not use_cache: logging.info("   ❌ [EMB] No Chinese detected.")

    status = "missing"
    detail = "No subs found"
    
    if has_ext: status = "ok"; detail = f"[外部] {ext_name}"
    elif has_emb_chi: status = "ok"; detail = emb_detail
    else:
        if emb_detail: detail = emb_detail
        
    logging.info(f"   🏁 [RESULT] Status: {status}")
    
    return {"name": ep_name, "status": status, "detail": detail, "media_info": media_info}

def process_folder_videos(client, full_path, all_files, existing_data=None):
    results = []
    root_path = "/Cloud"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f: root_path = json.load(f).get('path', '/Cloud')
    except: pass

    existing_map = {}
    if existing_data:
        try:
            for item in existing_data: existing_map[item['name']] = item
        except: pass

    video_files = sorted([f for f in all_files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)], key=lambda x: x['name'])
    
    for vid in video_files:
        cached_ep = existing_map.get(vid['name'])
        cached_info = cached_ep.get('media_info') if cached_ep else None
        result = _determine_video_status(vid['name'], all_files, full_path, root_path, cached_info)
        results.append(result)
        
    return results

def process_movie_item(client, drive_id, m_name, m_full_path, force=False):
    logging.info("=" * 60)
    logging.info(f"🎥 [MOVIE] {m_name}")
    
    existing_eps = None
    if not force:
        row = get_media_by_path(m_full_path)
        if row and row['all_subs']:
            try:
                data = json.loads(row['all_subs'])
                if data and len(data) > 0: existing_eps = json.loads(data[0]['subs'])
            except: pass

    files = client.list_files(m_full_path)
    if files is None: 
        logging.error(f"❌ Failed to list files for {m_full_path}")
        return False, False # (Exists, Success) -> (False, False)
        
    episodes = process_folder_videos(client, m_full_path, files, existing_eps)
    if episodes:
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': json.dumps(episodes)}])
        return True, True # Exists, Success
    return False, True # Not Exists (empty), Success

def process_tv_item(client, drive_id, t_name, t_full_path, force=False):
    logging.info("=" * 60)
    logging.info(f"📺 [TV] {t_name}")
    
    existing_season_map = {}
    row = get_media_by_path(t_full_path)
    if not force and row and row['all_subs']:
        try:
            data = json.loads(row['all_subs'])
            existing_season_map = {item['season']: item for item in data}
        except: pass
    
    seasons = client.list_files(t_full_path, refresh=force)
    if seasons is None:
        logging.error(f"❌ Failed to list seasons for {t_full_path}")
        return False, False # Error
        
    if not seasons: return False, True # Empty but success
    
    final_data = []
    
    for s in seasons:
        if not s['is_dir']: continue
        s_name = s['name']
        if "Season" not in s_name and "Specials" not in s_name: continue
        
        logging.info(f"   👉 [SCAN] {s_name}")
        s_path = posixpath.join(t_full_path, s_name)
        s_files = client.list_files(s_path, refresh=force)
        if not s_files: continue
        
        existing_eps = None
        if not force and s_name in existing_season_map:
            try: existing_eps = json.loads(existing_season_map[s_name]['subs'])
            except: pass
        
        episodes = process_folder_videos(client, s_path, s_files, existing_eps)
        if episodes: final_data.append({'season': s_name, 'subs': json.dumps(episodes)})

    if final_data:
        save_media('tv', drive_id, t_name, t_full_path, final_data)
        return True, True
    return False, True

def get_media_folders(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return {}
    folders = {}
    if row['type'] == 'movie': folders['Movie'] = row['full_path']
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
    
    ep_key_counts = Counter()
    for f in files:
        if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS):
            k = get_season_episode_key(f['name'])
            if k: ep_key_counts[k] += 1

    result = []
    for f in files:
        if f['is_dir']: continue
        fname = f['name']
        ext = os.path.splitext(fname)[1].lower()
        
        is_multi = False
        ftype = "📄 Other"
        
        if ext in VIDEO_EXTS: 
            ftype = "🎬 Video"
            k = get_season_episode_key(fname)
            if k and ep_key_counts[k] > 1: is_multi = True
        elif ext in SUB_EXTS: ftype = "📝 Subtitle"
        elif ext in IMG_EXTS: ftype = "🖼️ Info/Img"
        
        result.append({"name": fname, "type": ftype, "is_multi": is_multi})
        
    def sort_key(item):
        t = item['type']
        if "Video" in t: return 0
        if "Subtitle" in t: return 1
        return 3
    result.sort(key=lambda x: (sort_key(x), x['name']))
    return result

def execute_folder_rename(alist_url, token, folder_path):
    client = AlistClient(alist_url, token)
    logs = []
    logging.info(f"🔄 [Rename] Scanning: {folder_path}")
    files = client.list_files(folder_path, refresh=True)
    if not files: return ["❌ Read Error"]
    videos = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(VIDEO_EXTS)]
    subs = [f for f in files if not f['is_dir'] and f['name'].lower().endswith(SUB_EXTS)]
    
    if len(videos) == 1 and len(subs) >= 1:
        vid_base = os.path.splitext(videos[0]['name'])[0]
        for sub in subs:
            target = f"{vid_base}{os.path.splitext(sub['name'])[1]}"
            if sub['name'] != target and not any(f['name'] == target for f in files):
                if client.rename(posixpath.join(folder_path, sub['name']), target):
                    logs.append(f"✅ Rename: {sub['name']} -> {target}")
    else:
        for vid in videos:
            k = get_season_episode_key(vid['name'])
            if not k: continue
            vid_base = os.path.splitext(vid['name'])[0]
            for sub in subs:
                sk = get_season_episode_key(sub['name'])
                if sk and sk == k:
                    target = f"{vid_base}{os.path.splitext(sub['name'])[1]}"
                    if sub['name'] != target and not any(f['name'] == target for f in files):
                        if client.rename(posixpath.join(folder_path, sub['name']), target):
                            logs.append(f"✅ S{k[0]}E{k[1]}: {sub['name']} -> {target}")
    return logs if logs else ["✅ No changes needed"]

def execute_folder_upload(alist_url, token, folder_path, files_dict):
    client = AlistClient(alist_url, token)
    logs = []; uploaded = 0
    for name, content in files_dict.items():
        if not name.lower().endswith(SUB_EXTS): logs.append(f"⚠️ Skip: {name}"); continue
        if client.put_file(posixpath.join(folder_path, name), content):
            logs.append(f"✅ Upload: {name}"); uploaded += 1
    if uploaded == 0: return logs
    time.sleep(1.5); logs.extend(execute_folder_rename(alist_url, token, folder_path))
    return logs

def execute_file_deletion(alist_url, token, folder_path, file_names, alist_root="/Cloud"):
    client = AlistClient(alist_url, token); logs = []
    rclone_folder = RcloneHandler.map_path(folder_path, alist_root)
    if not rclone_folder.endswith('/'): rclone_folder += '/'
    if len(file_names) == 1:
        ok, err = RcloneHandler.delete_file_single(f"{rclone_folder}{file_names[0]}")
        logs.append(f"✅ Deleted: {file_names[0]}" if ok else f"❌ Error: {err}")
    else:
        ok, err = RcloneHandler.delete_files_batch(rclone_folder, file_names)
        logs.append(f"✅ Batch Deleted ({len(file_names)})" if ok else f"❌ Batch Error: {err}")
    client.list_files(folder_path, refresh=True)
    return logs

def execute_directory_purge(alist_url, token, folder_path, media_id, season_name, alist_root="/Cloud"):
    client = AlistClient(alist_url, token); logs = []
    rclone_folder = RcloneHandler.map_path(folder_path, alist_root)
    if not rclone_folder.endswith('/'): rclone_folder += '/'
    ok, err = RcloneHandler.purge_folder(rclone_folder)
    if ok:
        logs.append(f"✅ Purged: {folder_path}")
        delete_season_data(media_id, season_name)
        client.list_files(posixpath.dirname(folder_path), refresh=True)
    else: logs.append(f"❌ Purge Error: {err}")
    return logs

def import_subs_to_target(alist_url, token, source_folder, target_folder):
    client = AlistClient(alist_url, token)
    src_files = client.list_files(source_folder)
    subs = [f['name'] for f in src_files if f['name'].lower().endswith(SUB_EXTS)]
    if not subs: return "No subs found", []
    if client.copy(source_folder, target_folder, subs):
        time.sleep(1); execute_folder_rename(alist_url, token, target_folder)
        return "Done", []
    return "Failed", []

# [MODIFIED] run_library_scan now accepts target_path and includes safeguards
def run_library_scan(alist_url, token, target_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 Scan Started. Target: {target_path}")
    
    all_media = get_all_media("All", "")
    db_paths = {row['full_path']: row['id'] for row in all_media}
    found_paths = set()
    
    # Scanned Scopes: Paths that were successfully listed.
    # We only delete items if they fall under a successfully scanned scope.
    scanned_scopes = set()

    def scan_drive(drive_path, drive_id):
        # drive_path e.g. /Cloud/DriveA
        logging.info(f"👉 Scanning Drive: {drive_path}")
        sub_folders = client.list_files(drive_path)
        
        if sub_folders is None:
            logging.error(f"❌ Failed to list drive: {drive_path}. Skipping cleanup for this drive.")
            return False # Failed
            
        scanned_scopes.add(drive_path) # Mark this drive as successfully listed
        
        folder_map = {item['name'].lower(): item['name'] for item in sub_folders if item['is_dir']}
        
        # Movies
        if 'movies' in folder_map:
            m_path = posixpath.join(drive_path, folder_map['movies'])
            m_list = client.list_files(m_path)
            if m_list is not None:
                scanned_scopes.add(m_path)
                for m in m_list:
                    if not m['is_dir']: continue
                    full = posixpath.join(m_path, m['name'])
                    exists, success = process_movie_item(client, drive_id, m['name'], full, force=False)
                    if success and exists: found_paths.add(full)
            else:
                logging.error(f"❌ Failed to list movies folder: {m_path}")

        # TV
        if 'tv' in folder_map:
            t_path = posixpath.join(drive_path, folder_map['tv'])
            t_list = client.list_files(t_path)
            if t_list is not None:
                scanned_scopes.add(t_path)
                for t in t_list:
                    if not t['is_dir']: continue
                    full = posixpath.join(t_path, t['name'])
                    exists, success = process_tv_item(client, drive_id, t['name'], full, force=False)
                    if success and exists: found_paths.add(full)
            else:
                logging.error(f"❌ Failed to list TV folder: {t_path}")
        
        return True

    # Check if target is Root or specific Drive
    # We assume drives are direct children of /Cloud (or whatever start_cloud_path is in config, usually /Cloud)
    # If target_path is /Cloud, we list it to get drives.
    # If target_path is /Cloud/DriveA, we treat DriveA as the drive.
    
    # Simple logic: If target ends with /Cloud, treat as root. Else treat as specific drive.
    # But user might configure path=/MyData. 
    # Let's check config path.
    root_path = "/Cloud"
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f: root_path = json.load(f).get('path', '/Cloud')
    except: pass
    
    # Normalize paths
    target_path = target_path.rstrip('/')
    root_path = root_path.rstrip('/')
    
    if target_path == root_path:
        # Scanning Root
        drives = client.list_files(root_path)
        if drives is None:
            logging.error(f"❌ [Safeguard] Failed to list root {root_path}. Aborting scan.")
            return # Abort entire scan, delete nothing
        
        for d in drives:
            if d['is_dir']:
                scan_drive(posixpath.join(root_path, d['name']), d['name'])
    else:
        # Scanning Specific Target (Assuming it's a Drive folder)
        # drive_id is the basename of target_path
        drive_id = os.path.basename(target_path)
        scan_drive(target_path, drive_id)

    # Cleanup Logic with Safeguard
    with get_db_connection() as conn:
        deleted_count = 0
        for path, mid in db_paths.items():
            # Only delete if the path belongs to a scope that was successfully scanned
            # Check if path starts with any path in scanned_scopes
            in_scope = False
            for scope in scanned_scopes:
                if path.startswith(scope):
                    in_scope = True
                    break
            
            if in_scope:
                if path not in found_paths:
                    logging.info(f"🗑️ [CLEANUP] Removing missing media: {path}")
                    conn.execute("DELETE FROM media WHERE id = ?", (mid,))
                    deleted_count += 1
            # If not in_scope, we do nothing (preserve it)
            
        if deleted_count > 0:
            logging.info(f"🧹 Cleanup finished: Removed {deleted_count} items.")

    logging.info("🏁 Scan Finished!")

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return
    logging.info(f"🔄 Manual Refresh: {row['name']}")
    exists, success = False, False
    if row['type'] == 'movie': 
        exists, success = process_movie_item(client, row['drive_id'], row['name'], row['full_path'], force=False)
    elif row['type'] == 'tv': 
        exists, success = process_tv_item(client, row['drive_id'], row['name'], row['full_path'], force=False)
    
    # Only delete if scan was successful AND item no longer exists
    if success and not exists:
        logging.info(f"🗑️ [CLEANUP] Media became empty/invalid, removing: {row['name']}")
        with get_db_connection() as conn: conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    elif not success:
        logging.error(f"❌ Refresh failed for {row['name']} due to API error.")
        
    logging.info(f"🏁 Refresh Done: {row['name']}")
