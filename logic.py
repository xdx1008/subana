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
        data = self._request('post', 'list', {"path": path, "page": 1, "per_page": 0, "refresh": refresh})
        if data and data.get('code') == 200: return data['data']['content']
        return []

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
            # logging.info(f"   🕵️ [FFprobe] {file_url[:50]}...") 
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
        
        if not use_cache:
            logging.info(f"   🔍 [EMB] Found {sub_cnt} tracks: {media_info.get('Subtitle Languages')}")
        
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
    
    if has_ext:
        status = "ok"; detail = f"[外部] {ext_name}"
    elif has_emb_chi:
        status = "ok"; detail = emb_detail
    else:
        if emb_detail: detail = emb_detail
        
    logging.info(f"   🏁 [RESULT] Status: {status}")
    
    return {
        "name": ep_name,
        "status": status,
        "detail": detail,
        "media_info": media_info
    }

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
            for item in existing_data:
                existing_map[item['name']] = item
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
                if data and len(data) > 0:
                    existing_eps = json.loads(data[0]['subs'])
            except: pass

    files = client.list_files(m_full_path)
    if not files: return False
    
    episodes = process_folder_videos(client, m_full_path, files, existing_eps)
    if episodes:
        save_media('movie', drive_id, m_name, m_full_path, [{'season': 'Movie', 'subs': json.dumps(episodes)}])
        return True
    return False

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
    if not seasons: return False
    
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
            try:
                existing_eps = json.loads(existing_season_map[s_name]['subs'])
            except: pass
        
        episodes = process_folder_videos(client, s_path, s_files, existing_eps)
        if episodes:
            final_data.append({'season': s_name, 'subs': json.dumps(episodes)})

    if final_data:
        save_media('tv', drive_id, t_name, t_full_path, final_data)
        return True
    return False

# --- Operation Wrappers ---
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
        t = item['type']; 
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
        if not name.lower().endswith(SUB_EXTS):
            logs.append(f"⚠️ Skip: {name}"); continue
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

def run_library_scan(alist_url, token, start_cloud_path="/Cloud"):
    client = AlistClient(alist_url, token)
    logging.info("="*40)
    logging.info(f"🚀 Full Scan Started: {start_cloud_path}")
    
    all_media = get_all_media("All", "")
    db_paths = {row['full_path']: row['id'] for row in all_media}
    found_paths = set()

    drives = client.list_files(start_cloud_path)
    if drives:
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
                        
                        if process_movie_item(client, drive_id, m['name'], full, force=False):
                            found_paths.add(full)
            
            if 'tv' in folder_map:
                t_path = posixpath.join(drive_full_path, folder_map['tv']); t_list = client.list_files(t_path)
                if t_list:
                    for t in t_list:
                        if not t['is_dir']: continue
                        full = posixpath.join(t_path, t['name'])
                        
                        if process_tv_item(client, drive_id, t['name'], full, force=False):
                            found_paths.add(full)
    
    with get_db_connection() as conn:
        deleted_count = 0
        for path, mid in db_paths.items():
            if path not in found_paths:
                logging.info(f"🗑️ [CLEANUP] Removing missing media: {path}")
                conn.execute("DELETE FROM media WHERE id = ?", (mid,))
                deleted_count += 1
        if deleted_count > 0:
            logging.info(f"🧹 Cleanup finished: Removed {deleted_count} items.")

    logging.info("🏁 Scan Finished!")

def run_single_refresh(alist_url, token, media_id):
    client = AlistClient(alist_url, token)
    row = get_media_by_id(media_id)
    if not row: return
    
    logging.info(f"🔄 Manual Refresh: {row['name']}")
    
    exists = False
    if row['type'] == 'movie': 
        exists = process_movie_item(client, row['drive_id'], row['name'], row['full_path'], force=False)
    elif row['type'] == 'tv': 
        exists = process_tv_item(client, row['drive_id'], row['name'], row['full_path'], force=False)
    
    if not exists:
        logging.info(f"🗑️ [CLEANUP] Media became empty/invalid, removing: {row['name']}")
        with get_db_connection() as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
    
    logging.info(f"🏁 Refresh Done: {row['name']}")
}
}

{
type: uploaded file
fileName: test/frontend/src/App.vue
fullContent:
<template>
  <v-app theme="dark">
    <v-navigation-drawer 
      v-model="drawer" 
      :rail="!mobile && rail" 
      :temporary="mobile"
      :permanent="!mobile"
      expand-on-hover 
      color="#1E1E1E" 
      :width="260" 
      class="border-r border-grey-darken-3 d-flex flex-column"
      @update:rail="val => rail = val"
    >
      <v-list-item class="px-2 py-4">
        <div v-if="!rail || mobile" class="text-center fade-transition d-flex flex-column align-center">
             <img v-if="config.site_icon" :src="config.site_icon" style="max-height: 50px; max-width: 100%; border-radius: 4px;" class="mb-2" />
             <div class="text-h6 font-weight-black text-grey-lighten-2 text-wrap" style="line-height: 1.2;">
                 {{ config.site_name || 'SUBANA MGR' }}
             </div>
        </div>
        <div v-else class="text-center">
            <img v-if="config.site_icon" :src="config.site_icon" style="max-height: 32px; max-width: 32px; border-radius: 4px;" />
            <v-icon v-else color="primary" size="large">mdi-cloud-sync</v-icon>
        </div>
      </v-list-item>

      <v-divider class="mb-2"></v-divider>
      <v-list density="compact" nav class="flex-grow-1">
        <v-list-item prepend-icon="mdi-movie-open" title="Media Library" value="media" @click="changeView('media')" :active="currentView==='media'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-sync" title="Rclone Sync" value="sync" @click="changeView('sync')" :active="currentView==='sync'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-notebook-outline" title="System Logs" value="logs" @click="changeView('logs')" :active="currentView==='logs'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-cog" title="Settings" value="settings" @click="changeView('settings')" :active="currentView==='settings'" color="primary" rounded="lg"></v-list-item>
      </v-list>
      <template v-slot:append>
        <div v-if="(!rail || mobile)" class="pa-4 bg-grey-darken-4 border-t border-grey-darken-3 fade-transition">
            <div class="mb-4">
                <div class="text-caption font-weight-bold text-grey mb-2 d-flex align-center">
                    <v-icon size="x-small" class="mr-1">mdi-robot</v-icon> AUTOMATION STATUS
                </div>
                
                <div class="mb-2">
                    <div class="d-flex align-center text-caption text-grey-darken-1 mb-1">
                        <v-icon size="x-small" class="mr-1">mdi-sync</v-icon> SYNC
                        <v-spacer></v-spacer>
                        <v-progress-circular v-if="status.sync.running" indeterminate size="10" width="1" color="primary"></v-progress-circular>
                    </div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Last:</span><span class="mono-font">{{ status.sync.last }}</span></div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Next:</span><span class="mono-font text-primary">{{ status.sync.next }}</span></div>
                </div>

                <v-divider class="my-2 border-grey-darken-2"></v-divider>

                <div>
                     <div class="d-flex align-center text-caption text-grey-darken-1 mb-1">
                        <v-icon size="x-small" class="mr-1">mdi-radar</v-icon> SCAN
                        <v-spacer></v-spacer>
                        <v-progress-circular v-if="status.scan.running" indeterminate size="10" width="1" color="primary"></v-progress-circular>
                    </div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Last:</span><span class="mono-font">{{ status.scan.last }}</span></div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Next:</span><span class="mono-font text-primary">{{ status.scan.next }}</span></div>
                </div>
            </div>
            
            <v-divider class="mb-3"></v-divider>
            
            <div>
                <div class="d-flex justify-space-between align-center mb-2">
                     <div class="text-caption font-weight-bold text-grey d-flex align-center"><v-icon size="x-small" class="mr-1">mdi-cloud</v-icon> STORAGE</div>
                     <v-btn icon="mdi-refresh" size="x-small" variant="text" density="compact" @click="fetchStatus(true)" :loading="checkingSpace" color="grey" title="Refresh Space"></v-btn>
                </div>
                <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Free:</span><span class="mono-font text-white font-weight-bold">{{ status.space.free }}</span></div>
                <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Total:</span><span class="mono-font">{{ status.space.total }}</span></div>
            </div>
        </div>
      </template>
    </v-navigation-drawer>

    <v-main class="fill-height overflow-hidden" id="main-content">
      <div v-if="currentView === 'media'" class="d-flex flex-column h-100 w-100 overflow-hidden">
        <div class="px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3 d-flex align-center gap-2 flex-shrink-0">
             <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer"></v-app-bar-nav-icon>
             
             <v-text-field 
                v-model="search" 
                prepend-inner-icon="mdi-magnify" 
                label="Search..." 
                density="compact" 
                variant="outlined" 
                hide-details 
                class="mono-font flex-grow-1" 
                :style="mobile ? '' : 'max-width: 300px'"
                bg-color="#121212"
             ></v-text-field>

             <v-spacer class="hidden-sm-and-down"></v-spacer>

             <v-btn color="error" variant="text" size="small" @click="clearDB" style="min-width: 0;">
                 <v-icon start>mdi-delete-sweep</v-icon>
                 <span class="d-none d-sm-inline">Clear DB</span>
             </v-btn>
             
             <v-divider vertical class="mx-2"></v-divider>
             
             <v-btn color="primary" :loading="status.scan.running" @click="startScan" variant="tonal" style="min-width: 0;">
                 <v-icon start>mdi-radar</v-icon>
                 <span class="d-none d-sm-inline">{{ status.scan.running ? 'Scanning...' : 'Scan Library' }}</span>
             </v-btn>
        </div>
        <div class="flex-grow-1 w-100 bg-[#121212] overflow-hidden" style="min-height: 0;">
            <v-data-table 
              :headers="mediaHeaders" :items="mediaList" :search="search" density="compact" 
              class="bg-transparent h-100 sticky-header-table" fixed-header height="100%" hover 
              :items-per-page="15" :items-per-page-options="[15, 25, 50, 100, { value: -1, title: 'All' }]"
            >
                <template #item.actions="{ item }">
                    <div class="d-flex justify-end gap-1">
                        <v-btn icon="mdi-refresh" size="x-small" variant="text" color="grey" @click="refreshItem(getRaw(item))" title="Refresh"></v-btn>
                        <v-btn icon="mdi-folder-open" size="x-small" variant="text" color="info" @click="openFileManager(getRaw(item))" title="Files"></v-btn>
                        <v-btn icon="mdi-file-document-outline" size="x-small" variant="text" color="warning" @click="openDetails(getRaw(item))" title="Details"></v-btn>
                    </div>
                </template>
                <template #item.status="{ item }">
                    <v-chip size="x-small" :color="getRaw(item).status === 'OK' ? 'green' : 'red'" label variant="flat" class="font-weight-bold">{{ getRaw(item).status }}</v-chip>
                </template>
                <template #item.is_multi="{ item }">
                    <v-chip v-if="getRaw(item).is_multi" size="x-small" color="orange" variant="outlined" class="px-1" style="height: 20px;">Multi</v-chip>
                    <span v-else class="text-caption text-grey-darken-2">Single</span>
                </template>
                <template #item.drive="{ item }"><span class="text-caption text-grey">{{ getRaw(item).drive }}</span></template>
                <template #item.name="{ item }"><span class="text-body-2 font-weight-medium text-grey-lighten-1">{{ getRaw(item).name }}</span></template>
                <template #no-data>
                    <div class="d-flex flex-column align-center justify-center pa-8 text-grey mt-10">
                        <v-icon size="64" class="mb-4" color="grey-darken-3">mdi-database-off</v-icon>
                        <div class="text-h6 mb-2">Library is Empty</div>
                        <v-btn color="primary" variant="tonal" @click="startScan">Start Scan</v-btn>
                    </div>
                </template>
            </v-data-table>
        </div>
      </div>

      <div v-if="currentView === 'sync'" class="d-flex flex-column h-100 w-100 overflow-hidden">
        <div class="px-4 py-3 bg-grey-darken-4 border-b border-grey-darken-3 d-flex flex-wrap align-center justify-space-between gap-3 flex-shrink-0">
           <div class="d-flex flex-wrap align-center gap-3 w-100">
               <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
               
               <div class="d-flex flex-wrap align-center gap-4 flex-grow-1">
                   <div class="d-flex align-center gap-2" title="Upload Speed">
                       <v-icon color="primary" size="small">mdi-upload-network</v-icon>
                       <span class="text-caption text-grey font-weight-bold hidden-xs">Speed:</span>
                       <span class="text-subtitle-2 mono-font font-weight-bold text-blue-lighten-1">{{ syncData.speed }}</span>
                   </div>
                   <div class="d-flex align-center gap-2" title="ETA">
                       <v-icon color="info" size="small">mdi-timer-sand</v-icon>
                       <span class="text-caption text-grey font-weight-bold hidden-xs">ETA:</span>
                       <span class="text-subtitle-2 mono-font text-grey-lighten-1">{{ syncData.eta }}</span>
                   </div>
               </div>
               
               <div class="d-flex gap-2">
                   <v-btn variant="flat" size="small" color="success" :disabled="syncRunning" @click="startSync" class="font-weight-bold" style="min-width: 0;">
                        <v-icon start>mdi-play</v-icon><span class="d-none d-sm-inline">Sync</span>
                   </v-btn>
                   <v-btn variant="tonal" size="small" color="error" :disabled="!syncRunning" @click="stopSync" style="min-width: 0;">
                        <v-icon start>mdi-stop</v-icon><span class="d-none d-sm-inline">Stop</span>
                   </v-btn>
               </div>
           </div>
        </div>
        <div class="flex-grow-1 w-100 bg-[#121212] d-flex flex-column overflow-hidden relative">
            <div class="d-flex px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3 text-caption text-uppercase font-weight-bold text-grey flex-shrink-0">
                <div class="flex-grow-1">File Name</div><div style="width: 200px;" class="d-none d-sm-block">Progress</div><div class="text-right" style="width: 120px;">Speed</div>
            </div>
            <div class="flex-grow-1 w-100 overflow-y-auto">
                 <div v-for="(info, fname) in syncData.files" :key="fname" class="d-flex align-center px-4 py-1 border-b border-grey-darken-3 hover:bg-white/5 transition-colors">
                     <div class="flex-grow-1 d-flex align-center gap-2 overflow-hidden mr-4"><v-icon size="small" color="grey">mdi-file-outline</v-icon><span class="text-caption text-grey-lighten-1 text-truncate" :title="fname">{{ fname }}</span></div>
                     <div style="width: 200px;" class="d-none d-sm-block"><v-progress-linear :model-value="info.pct" color="primary" height="4" rounded></v-progress-linear></div>
                     <div class="text-right mono-font text-caption text-blue-lighten-2 ml-4" style="width: 120px;">{{ info.speed }}</div>
                 </div>
                 <div v-if="!syncRunning && Object.keys(syncData.files).length === 0" class="d-flex flex-column align-center justify-center fill-height text-grey-darken-3 opacity-50"><v-icon size="80" class="mb-4">mdi-cloud-sync-outline</v-icon><div class="text-h5 font-weight-bold">IDLE</div></div>
            </div>
        </div>
      </div>

      <div v-if="currentView === 'logs'" class="d-flex flex-column h-100 w-100 overflow-hidden bg-black">
         <div class="d-flex align-center px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3">
             <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
             <div class="text-subtitle-2 font-weight-bold text-grey-lighten-1">System Logs</div>
             <v-spacer></v-spacer>
             <div v-if="autoScrollPaused" class="text-caption text-warning d-flex align-center fade-transition">
                 <v-icon size="x-small" class="mr-1">mdi-pause-circle-outline</v-icon> Auto-scroll Paused
             </div>
         </div>
         
         <div 
            class="flex-grow-1 pa-4 overflow-y-auto" 
            ref="logBox"
            @wheel="handleLogUserInteraction"
            @touchmove="handleLogUserInteraction"
            @mousedown="handleLogUserInteraction"
            @keydown="handleLogUserInteraction"
         >
             <div v-if="!logContent" class="text-grey-darken-2 text-center mt-10">No logs available yet...</div>
             <div class="mono-font text-caption text-grey-lighten-1" style="white-space: pre-wrap; line-height: 1.5; font-family: 'Consolas', monospace;">{{ logContent }}</div>
         </div>
      </div>

      <v-container v-if="currentView === 'settings'" fluid class="pa-4 h-100 overflow-y-auto">
           <div class="d-flex align-center mb-4">
                <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
                <div class="text-h6">Settings</div>
           </div>
           
           <v-card color="#1E1E1E" title="Appearance" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.site_name" label="Site Name" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.site_icon" label="Site Icon URL (e.g. https://...)" variant="outlined" density="compact" bg-color="#222" prepend-inner-icon="mdi-link" hint="Enter a direct link to an image file" persistent-hint></v-text-field>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>
           
           <v-card color="#1E1E1E" title="System Logs" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.log_max_size" label="Max Log File Size (MB)" type="number" variant="outlined" density="compact" bg-color="#222" hint="Old logs will be overwritten when size limit is reached." persistent-hint></v-text-field>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Alist Connection" class="mb-4" border>
              <v-card-text>
                  <v-text-field v-model="config.url" label="Alist URL" variant="outlined" density="compact" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.token" label="Token" variant="outlined" density="compact" type="password" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.path" label="Cloud Root Path" variant="outlined" density="compact" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.rclone_conf" label="Rclone Config Path" variant="outlined" density="compact" bg-color="#222" hint="Absolute path inside container" persistent-hint></v-text-field>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Rclone Sync Configuration" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.local_path" label="Local Source Path" variant="outlined" density="compact" bg-color="#222" prepend-inner-icon="mdi-folder-home"></v-text-field>
                      </v-col>
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.remote_path" label="Remote Destination Path" variant="outlined" density="compact" bg-color="#222" prepend-inner-icon="mdi-cloud-upload"></v-text-field>
                      </v-col>
                  </v-row>
                  <v-row align="center">
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.transfers" label="Transfers (Threads)" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.bwlimit" label="Bandwidth Limit" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.sync_interval" label="Interval (Minutes)" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-switch v-model="config.auto_sync" label="Auto Sync (Timer)" color="success" hide-details inset></v-switch>
                          <div class="text-caption text-grey ml-2 mt-1">Runs every {{config.sync_interval}} mins</div>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Automation" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-switch v-model="config.auto_run" label="Enable Auto Library Scan" color="primary" hide-details inset></v-switch>
                          <div class="text-caption text-grey ml-2 mt-1">Automatically checks for new files in cloud folders.</div>
                      </v-col>
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.interval" label="Scan Interval (Seconds)" type="number" variant="outlined" density="compact" bg-color="#222" hide-details></v-text-field>
                          <div class="text-caption text-grey mt-1">Frequency of library updates (default: 3600s).</div>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <div class="d-flex justify-end pb-6">
               <v-btn color="primary" size="large" variant="flat" prepend-icon="mdi-content-save" @click="saveConfig">Save All Changes</v-btn>
           </div>
      </v-container>
      
      <v-dialog v-model="fmDialog" width="auto" max-width="95vw" scrollable>
        <v-card color="#1E1E1E">
            <v-card-title class="d-flex align-center text-subtitle-1 border-b border-grey-darken-3 bg-[#252525]">
                <div class="d-flex align-center overflow-hidden mr-2">
                    <v-icon start color="primary">mdi-folder</v-icon> 
                    <span class="text-truncate">{{ selectedMedia?.name }}</span>
                    <v-chip size="x-small" class="ml-2" color="grey-lighten-1" variant="flat">{{ fileList.length }} items</v-chip>
                </div>
                <v-spacer></v-spacer>
                <v-select v-model="currentFolder" :items="folderList" item-title="label" item-value="path" density="compact" variant="outlined" hide-details style="max-width: 300px" bg-color="#121212" @update:model-value="loadFiles"></v-select>
            </v-card-title>
            <v-card-text class="pa-0" style="height: 500px;">
                <v-data-table v-model="selectedFiles" show-select :headers="fmHeaders" :items="fileList" density="compact" item-value="name" class="bg-transparent" fixed-header height="100%" hover items-per-page="-1">
                    <template #item.name="{ item }"><span class="text-no-wrap">{{ getRaw(item).name }}</span></template>
                    <template #item.type="{ item }"><span class="text-caption text-grey text-no-wrap">{{ getRaw(item).type }}</span></template>
                    <template #bottom></template>
                </v-data-table>
            </v-card-text>
            <v-divider></v-divider>
            <v-card-actions class="bg-[#252525]">
                <v-file-input ref="fileInput" v-model="uploadFiles" multiple hide-input style="display:none" @update:modelValue="uploadSubtitles"></v-file-input>
                <v-btn color="blue" prepend-icon="mdi-upload" variant="text" @click="$refs.fileInput.click()">Upload Subs</v-btn>
                <v-spacer></v-spacer>
                <v-btn color="warning" variant="text" @click="runRename">Align Names</v-btn>
                <v-btn color="error" variant="text" @click="runDelete" :disabled="selectedFiles.length === 0">Delete {{ selectedFiles.length > 0 ? `(${selectedFiles.length})` : '' }}</v-btn>
                <v-btn color="red" variant="tonal" @click="runPurge">Purge Folder</v-btn>
                <v-btn @click="fmDialog = false">Close</v-btn>
            </v-card-actions>
        </v-card>
      </v-dialog>
      
      <v-dialog v-model="detailsDialog" max-width="1000px" scrollable>
        <v-card color="#1E1E1E">
            <v-card-title class="d-flex align-center border-b border-grey-darken-3 bg-[#252525]">
                <v-icon start color="warning">mdi-movie-open</v-icon> {{ selectedMedia?.name }}
                <v-spacer></v-spacer>
                <v-btn icon="mdi-close" variant="text" size="small" @click="detailsDialog = false"></v-btn>
            </v-card-title>
            <v-card-text class="pa-4 bg-[#121212]" style="max-height: 70vh;">
                <div v-if="!detailData || !detailData.seasons || detailData.seasons.length === 0" class="text-center text-grey py-8">No details.</div>
                <div v-else>
                    <div v-for="(season, i) in detailData.seasons" :key="i" class="mb-2">
                        <div 
                          v-if="detailData.info.type !== 'movie'"
                          class="d-flex align-center cursor-pointer pa-2 rounded hover-bg"
                          @click="season.expanded = !season.expanded"
                        >
                            <v-icon :class="{'rotate-90': season.expanded}" class="transition-transform mr-2" size="small">mdi-chevron-right</v-icon>
                            <div class="text-subtitle-2 font-weight-bold text-primary">{{ season.season }}</div>
                            <v-chip size="x-small" :color="season.okCount === season.totalCount ? 'green' : 'grey'" variant="outlined" class="font-weight-bold ml-2">
                                {{ season.okCount }} / {{ season.totalCount }}
                            </v-chip>
                        </div>

                        <v-expand-transition>
                            <div 
                              v-show="season.expanded" 
                              :class="detailData.info.type !== 'movie' ? 'ml-4 pl-2 border-l border-grey-darken-3' : ''"
                            >
                                <v-card v-for="(ep, j) in season.episodes" :key="j" variant="flat" color="transparent" class="mb-1 py-1">
                                    <div class="d-flex align-center px-2">
                                        <v-icon :color="ep.status === 'ok' ? 'green' : 'red'" size="small" class="mr-3">{{ ep.status === 'ok' ? 'mdi-check-circle' : 'mdi-alert-circle' }}</v-icon>
                                        <div class="flex-grow-1" style="min-width: 0;">
                                            <div class="text-body-2 font-weight-medium text-truncate text-grey-lighten-1">{{ ep.name }}</div>
                                            
                                            <div class="d-flex flex-wrap gap-1 mt-1" v-if="ep.media_info && !ep.media_info.error">
                                                <v-chip size="x-small" color="blue-grey" variant="tonal" class="info-badge" v-if="ep.media_info.Duration">⏱ {{ ep.media_info.Duration }}</v-chip>
                                                <v-chip size="x-small" color="indigo" variant="tonal" class="info-badge">{{ ep.media_info.Resolution }}</v-chip>
                                                <v-chip size="x-small" color="deep-purple" variant="tonal" class="info-badge" v-if="ep.media_info['Video Codec']">{{ ep.media_info['Video Codec'] }}</v-chip>
                                                <v-chip size="x-small" color="teal" variant="tonal" class="info-badge" v-if="ep.media_info['Frame Rate'] !== 'N/A'">{{ ep.media_info['Frame Rate'] }}</v-chip>
                                                <v-chip size="x-small" color="cyan" variant="tonal" class="info-badge" v-if="ep.media_info['Bit Depth']">{{ ep.media_info['Bit Depth'] }}</v-chip>
                                                <v-chip size="x-small" v-if="ep.media_info['Video Dynamic Range'] !== 'SDR'" color="purple" variant="tonal" class="info-badge">{{ ep.media_info['Video Dynamic Range'] }}</v-chip>
                                                <v-chip size="x-small" color="orange" variant="tonal" class="info-badge" v-if="ep.media_info['Audio Codec']">{{ ep.media_info['Audio Codec'] }}</v-chip>
                                                <span class="text-caption text-grey ml-2 mono-font align-self-center">{{ ep.media_info.Size }}</span>
                                            </div>

                                            <div class="d-flex align-center mt-1" v-if="ep.detail">
                                                <v-icon size="x-small" class="mr-1" color="grey">mdi-subtitles</v-icon>
                                                <v-chip v-if="ep.detail.includes('[外部]')" size="x-small" color="amber" label variant="flat" class="mr-1 px-1 font-weight-bold" style="height:16px; font-size: 10px;">EXT</v-chip>
                                                <v-chip v-if="ep.detail.includes('[內嵌]')" size="x-small" color="blue-grey" label variant="flat" class="mr-1 px-1 font-weight-bold" style="height:16px; font-size: 10px;">EMB</v-chip>
                                                <span class="text-caption text-grey-lighten-1 text-wrap" style="word-break: break-word;">{{ ep.detail.replace('[外部]', '').replace('[內嵌]', '').trim() }}</span>
                                            </div>

                                        </div>
                                    </div>
                                </v-card>
                            </div>
                        </v-expand-transition>
                    </div>
                </div>
            </v-card-text>
        </v-card>
      </v-dialog>

    <v-snackbar v-model="snackbar" :timeout="3000" color="grey-darken-3">{{ snackbarText }}<template v-slot:actions><v-btn color="white" variant="text" @click="snackbar = false">Close</v-btn></template></v-snackbar>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, onUnmounted, computed } from 'vue'
import { useDisplay } from 'vuetify'
import axios from 'axios'

const { mobile } = useDisplay()

const drawer = ref(true); 
const rail = ref(true); 
const currentView = ref('media'); 
const config = ref({}); 
// [MODIFIED] Added sync.last and sync.next to initial state
const status = reactive({ 
    space: { free: '?', total: '?' }, 
    scan: { last: '...', next: '...', running: false },
    sync: { last: '...', next: '...', running: false }
}); 
const checkingSpace = ref(false); const snackbar = ref(false); const snackbarText = ref('')
const showMsg = (msg) => { console.log(`[UI] ${msg}`); snackbarText.value = msg; snackbar.value = true }
const syncRunning = ref(false); const syncData = reactive({ speed: '0 B/s', eta: '-', total: '0 / 0', progress: 0, files: {} }); const logContent = ref(""); const logBox = ref(null); let logPoller = null; let statusPoller = null;
const search = ref(''); const mediaList = ref([])
const mediaHeaders = [ 
    { title: 'Type', key: 'type', width: '80px', sortable: true }, 
    { title: 'Drive', key: 'drive', width: '100px', sortable: true },
    { title: 'Status', key: 'status', width: '80px', sortable: true }, 
    { title: 'Ver.', key: 'is_multi', align: 'center', width: '80px', sortable: true }, 
    { title: 'Name', key: 'name', sortable: true }, 
    { title: 'Actions', key: 'actions', align: 'end', sortable: false, width: '130px' } 
]
const fmHeaders = [ { title: 'Name', key: 'name', align: 'start', sortable: true }, { title: 'Type', key: 'type', width: '120px', align: 'end', sortable: true } ]
const getRaw = (item) => item && item.raw ? item.raw : item
const fmDialog = ref(false); const detailsDialog = ref(false); const selectedMedia = ref(null); const detailData = ref(null); const folderList = ref([]); const currentFolder = ref(''); const fileList = ref([]); const selectedFiles = ref([]); const uploadFiles = ref([])

// [MODIFIED] New state for Log Pause
const autoScrollPaused = ref(false)
let logPauseTimer = null

axios.defaults.baseURL = '/'
const fetchConfig = async () => { try { const r = await axios.get('api/config'); config.value = r.data } catch(e){ console.error(e) } }
const saveConfig = async () => { try { await axios.post('api/config', config.value); showMsg('Settings Saved'); await fetchConfig(); await fetchStatus() } catch(e) { showMsg('Error'); console.error(e) } }
const fetchStatus = async (force=false) => { if(force) checkingSpace.value=true; try { const r = await axios.get(`api/status?refresh_space=${force}`); Object.assign(status, r.data); if(force) showMsg('Space Updated') } catch(e){ console.error(e) } finally { checkingSpace.value = false } }
const fetchLogs = async () => { try { const r = await axios.get('api/logs'); logContent.value = r.data.logs.join(''); nextTick(() => { if(!autoScrollPaused.value && logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight }) } catch(e) {} }
const startLogPolling = () => { stopLogPolling(); fetchLogs(); logPoller = setInterval(fetchLogs, 2000) }
const stopLogPolling = () => { if (logPoller) clearInterval(logPoller); logPoller = null }

const changeView = (view) => { 
    currentView.value = view
    if (mobile.value) {
        drawer.value = false
    }
}

// [MODIFIED] Helper for scrolling to bottom
const scrollToBottom = () => {
    if (logBox.value) {
        logBox.value.scrollTop = logBox.value.scrollHeight
    }
}

// [MODIFIED] Handle User Interaction with Logs
const handleLogUserInteraction = () => {
    // 1. Pause auto-scroll immediately
    autoScrollPaused.value = true
    
    // 2. Reset existing timer
    if (logPauseTimer) clearTimeout(logPauseTimer)
    
    // 3. Set new 10-second timer to resume
    logPauseTimer = setTimeout(() => {
        autoScrollPaused.value = false
        scrollToBottom()
    }, 10000)
}

watch(currentView, (newVal) => { if (newVal === 'logs') startLogPolling(); else stopLogPolling() })
const startSync = () => { if (ws && ws.readyState === 1) { ws.send("start_sync"); showMsg('Sync Started') } else showMsg('WS Disconnected') }
const stopSync = async () => { try { await axios.post('api/sync/stop'); showMsg('Sync Stopped'); await fetchConfig(); } catch(e){ console.error(e) } }
const startScan = async () => { try { await axios.post('api/scan'); showMsg('Scan Started') } catch(e){ showMsg('Error'); console.error(e) } }

const loadMedia = async () => { try { const r = await axios.get('api/media'); mediaList.value = r.data } catch(e){ mediaList.value=[] } }
const clearDB = async () => { if(confirm('Clear DB?')) { try { await axios.post('api/media/clear'); showMsg('Cleared'); await loadMedia() } catch(e){ console.error(e) } } }
const refreshItem = async (data) => { if(data){ showMsg(`Refreshing: ${data.name}...`); try { await axios.post(`api/media/${data.id}/refresh`); showMsg(`Refreshed: ${data.name}`); await loadMedia() } catch(e){ showMsg('Error') } } }
const openDetails = async (data) => { 
    if(data){ 
        selectedMedia.value=data
        try { 
            const r = await axios.get(`api/media/${data.id}`)
            if(r.data.seasons) {
                const isMovie = r.data.info.type === 'movie'
                r.data.seasons.forEach(s => {
                    s.expanded = isMovie 
                    s.totalCount = s.episodes.length
                    s.okCount = s.episodes.filter(e => e.status === 'ok').length
                })
            }
            detailData.value = r.data
            detailsDialog.value=true 
        } catch(e) {} 
    } 
}
const openFileManager = async (data) => { if(data){ selectedMedia.value=data; try { const r = await axios.get(`api/media/${data.id}/folders`); folderList.value=r.data; if(folderList.value.length>0){ currentFolder.value=folderList.value[0].path; loadFiles() }; fmDialog.value=true } catch(e) {} } }
const loadFiles = async () => { try { const r = await axios.get(`api/files?path=${encodeURIComponent(currentFolder.value)}`); fileList.value=r.data; selectedFiles.value=[] } catch(e){ fileList.value=[] } }
const runDelete = async () => { if(confirm('Delete?')){ showMsg('Deleting...'); try { await axios.post('api/media/delete', {media_id:selectedMedia.value.id, folder_path:currentFolder.value, files:selectedFiles.value}); showMsg('Deleted'); loadFiles(); await loadMedia() } catch(e){ showMsg('Error') } } }
const runRename = async () => { showMsg('Renaming...'); try { await axios.post('api/media/rename', {media_id:selectedMedia.value.id, folder_path:currentFolder.value}); showMsg('Renamed'); loadFiles(); await loadMedia() } catch(e){ showMsg('Error') } }
const runPurge = async () => { if(confirm('Purge?')){ showMsg('Purging...'); try { const sk = folderList.value.find(f=>f.path===currentFolder.value)?.label; await axios.post('api/media/purge', {media_id:selectedMedia.value.id, folder_path:currentFolder.value, season_key:sk}); showMsg('Purged'); fmDialog.value=false; loadMedia() } catch(e){ showMsg('Error') } } }
const uploadSubtitles = async (files) => { if (!files || files.length === 0) return; const formData = new FormData(); formData.append('media_id', selectedMedia.value.id); formData.append('folder_path', currentFolder.value); for (let i = 0; i < files.length; i++) { formData.append('files', files[i]) }; showMsg(`Uploading...`); try { await axios.post('api/media/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }); showMsg('Upload Success'); uploadFiles.value = []; loadFiles(); await loadMedia() } catch (e) { showMsg('Upload Failed'); console.error(e) } }

const formatTime = (ts) => { if (!ts) return 'Never'; const d = new Date(ts * 1000); return d.toLocaleString('zh-TW', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12: false}) }

let ws = null
const connectWs = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${protocol}//${location.host}/ws/sync`)
    ws.onmessage = (e) => {
        const d = JSON.parse(e.data)
        if(d.type==='update'){ syncRunning.value=d.running; Object.assign(syncData, d.data); syncData.files=d.files }
        else if(d.type==='log'){ 
            if(currentView.value === 'logs') {
                logContent.value += d.msg + '\n'
                // [MODIFIED] Only scroll if not paused
                nextTick(() => { 
                    if (!autoScrollPaused.value) scrollToBottom() 
                })
            }
        }
        else if(d.type==='refresh_space'){ fetchStatus(true); showMsg('Sync Finished'); fetchConfig() }
    }
    ws.onclose = () => setTimeout(connectWs, 2000)
}

watch(() => status.scan.running, (newVal, oldVal) => {
    if (oldVal === true && newVal === false) {
        showMsg('Library Scan Finished');
        loadMedia();
    }
});

watch(() => config.value.site_name, (newVal) => {
    document.title = newVal || 'Subana Manager';
}, { immediate: true });

watch(() => config.value.site_icon, (newVal) => {
    let link = document.querySelector("link[rel~='icon']");
    if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
    }
    link.href = newVal || '/favicon.ico';
}, { immediate: true });

onMounted(() => { 
    if (mobile.value) {
        drawer.value = false;
    }

    fetchConfig(); 
    fetchStatus(); 
    loadMedia(); 
    connectWs(); 
    if (currentView.value === 'logs') startLogPolling();
    
    statusPoller = setInterval(() => {
        fetchStatus();
    }, 3000);
})

onUnmounted(() => {
    stopLogPolling();
    if (statusPoller) clearInterval(statusPoller);
})
</script>

<style>
/* ... existing styles ... */
html, body { overflow: hidden; height: 100%; margin: 0; background: #121212; }
#app { height: 100%; }
.v-application { height: 100%; display: flex; flex-direction: column; }
.v-main { height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
.mono-font { font-family: 'Roboto Mono', monospace; }
.sticky-header-table .v-data-table__th { background: #1E1E1E !important; white-space: nowrap; z-index: 10; }
.info-badge { font-size: 10px; font-weight: bold; border: 1px solid rgba(255,255,255,0.2); }
.fade-transition { transition: opacity 0.2s ease-in-out; }
.rotate-90 { transform: rotate(90deg); }
.transition-transform { transition: transform 0.2s; }
.cursor-pointer { cursor: pointer; }
.hover-bg:hover { background-color: rgba(255,255,255,0.05); }

@media (max-width: 600px) {
  .hidden-xs { display: none !important; }
}
</style>
}
