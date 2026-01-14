import os
import json
import asyncio
import time
import re
import logging
import shutil
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from collections import deque
from fastapi import FastAPI, WebSocket, Request, BackgroundTasks, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from contextlib import asynccontextmanager

from logic import (
    RcloneHandler, run_library_scan, 
    run_single_refresh, get_media_folders, list_folder_files,
    execute_file_deletion, execute_folder_rename, execute_directory_purge,
    execute_folder_upload, get_season_episode_key, get_cloud_drives
)
from database import get_all_media, get_media_by_id, get_subtitles, clear_db

# Constants
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

# --- Custom Log Handler ---
class OverwriteRotatingFileHandler(RotatingFileHandler):
    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        if os.path.exists(self.baseFilename):
            try: os.remove(self.baseFilename)
            except OSError: pass
        self.stream = self._open()

# --- App State ---
class AppState:
    def __init__(self):
        self.sync_running = False
        self.scan_running = False
        self.sync_data = {"speed": "0 B/s", "eta": "-", "total": "0 / 0", "progress": 0.0}
        self.active_files = {}
        self.remote_free = "Unknown"
        self.remote_total = "Unknown"

state = AppState()

# --- Config Helper ---
def load_config():
    defaults = {
        "url": "", "token": "", "path": "/Cloud", 
        "local_path": "/media", "remote_path": "union:", 
        "bwlimit": "30M", "transfers": "4", "min_age": "1m", 
        "auto_sync": False, "auto_run": False, "interval": 3600,
        "last_free": "Unknown", "last_total": "Unknown",
        "sync_interval": 60, "last_sync_ts": 0, "last_scan_time": 0,
        "rclone_conf": "/root/.config/rclone/rclone.conf",
        "site_name": "SUBANA MGR",
        "site_icon": "",
        "log_max_size": 2
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return {**defaults, **json.load(f)}
        except: pass
    return defaults

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def setup_logging(max_size_mb):
    max_bytes = int(max_size_mb * 1024 * 1024)
    if max_bytes <= 0: max_bytes = 1024 * 1024 
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for handler in root_logger.handlers[:]: root_logger.removeHandler(handler)
    file_handler = OverwriteRotatingFileHandler(LOG_FILE, maxBytes=max_bytes, backupCount=0, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S'))
    backup_file = f"{LOG_FILE}.1"
    if os.path.exists(backup_file):
        try: os.remove(backup_file)
        except: pass
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%H:%M:%S'))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

logger = logging.getLogger("server")

def format_ts_str(ts):
    if ts == 0: return "Never"
    return datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')

def get_scan_info_str(cfg):
    last_ts = cfg.get('last_scan_time', 0)
    interval = int(cfg.get('interval', 3600))
    auto = cfg.get('auto_run', False)
    last_str = format_ts_str(last_ts)
    next_str = "Disabled"
    if auto:
        next_ts = last_ts + interval
        if next_ts < time.time(): next_str = "Pending..."
        else: next_str = datetime.fromtimestamp(next_ts).strftime('%m-%d %H:%M')
    return last_str, next_str

def get_sync_info_str(cfg):
    last_ts = cfg.get('last_sync_ts', 0)
    interval_min = int(cfg.get('sync_interval', 60))
    auto = cfg.get('auto_sync', False)
    last_str = format_ts_str(last_ts)
    next_str = "Disabled"
    if auto:
        next_ts = last_ts + (interval_min * 60)
        if next_ts < time.time(): next_str = "Pending..."
        else: next_str = datetime.fromtimestamp(next_ts).strftime('%m-%d %H:%M')
    return last_str, next_str

# --- Shared Logic Functions ---
async def perform_library_scan(target=None):
    global state
    if state.scan_running: return
    state.scan_running = True
    cfg = load_config()
    target_path = target if target else cfg['path']
    try:
        logger.info(f"🚀 Library Scan Started (Target: {target_path})")
        await asyncio.to_thread(run_library_scan, cfg['url'], cfg['token'], target_path)
        
        if target_path == cfg['path']:
            cfg = load_config()
            cfg['last_scan_time'] = time.time()
            save_config(cfg)
            
        logger.info("🏁 Library Scan Finished")
    except Exception as e: logger.error(f"Scan Error: {e}")
    finally: state.scan_running = False

async def perform_rclone_sync():
    global state
    if state.sync_running:
        logger.warning("⚠️ Sync skipped: Job already running.")
        return
    state.sync_running = True
    state.active_files = {}
    state.sync_data = {"speed": "Calculating...", "eta": "-", "total": "0 / 0", "progress": 0.0}
    cfg = load_config()
    cfg['last_sync_ts'] = time.time()
    save_config(cfg)
    logger.info("🚀 Rclone Sync Started")
    try:
        re_global = re.compile(r'Transferred:\s+([\d.]+\s+\w+)\s+/\s+([\d.]+\s+\w+),\s+(\d+)%,\s+([\d.]+\s+\w+/s),\s+ETA\s+(\S+)')
        re_file = re.compile(r'\*\s+(.+):\s+(\d+)%\s+/\s*([\d.]+\w+),\s+([\d.]+\w+/s),\s+(\S+)')
        iterator = RcloneHandler.run_sync_process(
            cfg.get('local_path'), cfg.get('remote_path'),
            cfg.get('bwlimit'), cfg.get('min_age'), cfg.get('transfers')
        )
        for line in iterator:
            line = line.strip()
            if line:
                if "Transferred:" not in line and "ETA" not in line and not line.startswith("*") and not line.endswith(":"):
                        logger.info(f"[Rclone] {line}")
            m = re_global.search(line)
            if m: state.sync_data = {"total": f"{m.group(1)} / {m.group(2)}", "progress": float(m.group(3)), "speed": m.group(4), "eta": m.group(5)}
            m = re_file.search(line)
            if m:
                fname = os.path.basename(m.group(1).strip())
                state.active_files[fname] = {"pct": int(m.group(2)), "speed": m.group(4), "ts": time.time()}
            now = time.time()
            to_del = [k for k,v in state.active_files.items() if v['pct']>=100 or (now - v['ts']>10)]
            for k in to_del: del state.active_files[k]
            await asyncio.sleep(0.01)
        logger.info("✅ Rclone Sync Finished")
        try:
            free, total = await asyncio.to_thread(RcloneHandler.get_remote_free_space, cfg.get('remote_path'))
            state.remote_free = free; state.remote_total = total
            cfg = load_config(); cfg['last_free'] = free; cfg['last_total'] = total; save_config(cfg)
        except: pass
    except Exception as e: logger.error(f"Sync Error: {e}")
    finally:
        state.sync_running = False; state.active_files = {}; state.sync_data = {"speed": "Idle", "eta": "-", "total": "-", "progress": 0}

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    setup_logging(cfg.get('log_max_size', 2))
    state.remote_free = cfg.get('last_free', 'Unknown')
    state.remote_total = cfg.get('last_total', 'Unknown')
    asyncio.create_task(background_scheduler())
    yield

async def background_scheduler():
    logger.info("⏳ Scheduler Started")
    while True:
        try:
            await asyncio.sleep(60) 
            cfg = load_config()
            now = time.time()
            if cfg.get('auto_run', False) and not state.scan_running:
                interval = int(cfg.get('interval', 3600))
                last_scan = cfg.get('last_scan_time', 0)
                if interval > 0 and (now - last_scan > interval or last_scan == 0):
                    logger.info("⏰ Scheduler: Triggering Auto Scan")
                    asyncio.create_task(perform_library_scan())
            if cfg.get('auto_sync', False) and not state.sync_running:
                sync_int_sec = int(cfg.get('sync_interval', 60)) * 60
                last_sync = cfg.get('last_sync_ts', 0)
                if sync_int_sec > 0 and (now - last_sync > sync_int_sec or last_sync == 0):
                    logger.info("⏰ Scheduler: Triggering Auto Sync")
                    asyncio.create_task(perform_rclone_sync())
        except Exception as e: logger.error(f"Scheduler Error: {e}")

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ConfigModel(BaseModel):
    url: str = ""; token: str = ""; path: str = ""; local_path: str = ""; remote_path: str = ""
    bwlimit: str = ""; transfers: str = ""; min_age: str = ""; auto_sync: bool = False; auto_run: bool = False
    interval: int = 3600; last_free: str = "Unknown"; last_total: str = "Unknown"; sync_interval: int = 60
    last_scan_time: float = 0; last_sync_ts: float = 0; rclone_conf: str = "/root/.config/rclone/rclone.conf"
    site_name: str = "SUBANA MGR"; site_icon: str = ""; log_max_size: int = 2

class DeleteFileModel(BaseModel):
    media_id: int; folder_path: str; files: List[str]
class RenameModel(BaseModel):
    media_id: int; folder_path: str
class PurgeModel(BaseModel):
    media_id: int; folder_path: str; season_key: Optional[str] = ""

@app.get("/")
async def get_index(): return FileResponse("static/index.html")
@app.get("/api/config")
async def get_config(): return load_config()
@app.post("/api/config")
async def update_config(config: ConfigModel, background_tasks: BackgroundTasks):
    current_cfg = load_config()
    trigger_scan = False; trigger_sync = False
    if config.auto_run and config.last_scan_time == 0 and not state.scan_running: trigger_scan = True
    if config.auto_sync and config.last_sync_ts == 0 and not state.sync_running: trigger_sync = True
    if config.log_max_size != current_cfg.get('log_max_size'):
        logger.info(f"📝 Updating log size limit to {config.log_max_size} MB")
        setup_logging(config.log_max_size)
    save_config(config.dict())
    logger.info("⚙️ Settings updated")
    if trigger_scan: logger.info("🆕 First-run Scan triggered"); background_tasks.add_task(perform_library_scan)
    if trigger_sync: logger.info("🆕 First-run Sync triggered"); background_tasks.add_task(perform_rclone_sync)
    return {"status": "ok"}

@app.get("/api/status")
async def get_status(refresh_space: bool = False):
    cfg = load_config()
    if refresh_space:
        try:
            logger.info("🔄 [Space] Checking remote storage usage...")
            free, total = await asyncio.to_thread(RcloneHandler.get_remote_free_space, cfg.get('remote_path'))
            state.remote_free = free; state.remote_total = total
            cfg['last_free'] = free; cfg['last_total'] = total; save_config(cfg)
            logger.info(f"✅ [Space] Updated: Free {free} / Total {total}")
        except Exception as e: logger.error(f"❌ [Space] Check Error: {e}")
    scan_last, scan_next = get_scan_info_str(cfg)
    sync_last, sync_next = get_sync_info_str(cfg)
    if state.scan_running: scan_next = "Scanning..."
    return {"space": {"free": state.remote_free, "total": state.remote_total}, "scan": {"last": scan_last, "next": scan_next, "running": state.scan_running}, "sync": {"last": sync_last, "next": sync_next, "running": state.sync_running}}

@app.get("/api/logs")
async def get_logs():
    if not os.path.exists(LOG_FILE): return {"logs": ["Log file not found."]}
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            lines = deque(f, maxlen=1000); return {"logs": list(lines)}
    except Exception as e: return {"logs": [f"Error reading logs: {e}"]}

@app.post("/api/scan")
async def trigger_scan(background_tasks: BackgroundTasks, target: Optional[str] = None):
    if state.scan_running: return {"status": "running"}
    background_tasks.add_task(perform_library_scan, target)
    return {"status": "started", "target": target or "Full"}

@app.get("/api/drives")
async def get_drives_list():
    cfg = load_config()
    drives = await asyncio.to_thread(get_cloud_drives, cfg['url'], cfg['token'], cfg['path'])
    return drives

@app.get("/api/media")
async def list_media():
    try:
        raw = await asyncio.to_thread(get_all_media, "All", "")
        results = []
        for r in raw:
            is_ok = (r['all_subs'] and "missing" not in r['all_subs'])
            is_multi = False
            try:
                if r['all_subs']:
                    subs_data = json.loads(r['all_subs'])
                    if r['type'] == 'movie':
                        if len(json.loads(subs_data[0]['subs'])) > 1: is_multi = True
                    elif r['type'] == 'tv':
                        for season in subs_data:
                            eps = json.loads(season['subs'])
                            seen_keys = set()
                            for ep in eps:
                                k = get_season_episode_key(ep['name'])
                                if k:
                                    if k in seen_keys: is_multi = True; break
                                    seen_keys.add(k)
                            if is_multi: break
            except: pass
            results.append({"id": r['id'], "type": r['type'], "name": r['name'], "drive": r['drive_id'], "status": "OK" if is_ok else "Missing", "is_multi": is_multi})
        return results
    except: return []

@app.get("/api/media/{mid}")
async def get_media_detail(mid: int):
    try:
        subs = await asyncio.to_thread(get_subtitles, mid)
        row = await asyncio.to_thread(get_media_by_id, mid)
        if not row: raise HTTPException(404)
        parsed_subs = []
        if subs:
            for s in subs:
                try: parsed_subs.append({"season": s['season'], "episodes": json.loads(s['subs'])})
                except: pass
        return {"info": {"id": row['id'], "name": row['name'], "type": row['type'], "full_path": row['full_path']}, "seasons": parsed_subs}
    except: return {"info": {}, "seasons": []}

@app.post("/api/media/{mid}/refresh")
async def refresh_media(mid: int):
    logger.info(f"🔄 Refreshing media item {mid}...")
    cfg = load_config()
    await asyncio.to_thread(run_single_refresh, cfg['url'], cfg['token'], mid)
    return {"status": "ok"}

@app.post("/api/media/clear")
async def clear_database():
    logger.info("🗑️ Clearing database...")
    await asyncio.to_thread(clear_db)
    return {"status": "cleared"}

@app.get("/api/media/{mid}/folders")
async def get_media_dirs(mid: int):
    cfg = load_config()
    folders = await asyncio.to_thread(get_media_folders, cfg['url'], cfg['token'], mid)
    return [{"label": k, "path": v} for k, v in folders.items()]

@app.get("/api/files")
async def get_files(path: str):
    cfg = load_config()
    return await asyncio.to_thread(list_folder_files, cfg['url'], cfg['token'], path)

@app.post("/api/media/delete")
async def delete_files(data: DeleteFileModel):
    cfg = load_config()
    logs = await asyncio.to_thread(execute_file_deletion, cfg['url'], cfg['token'], data.folder_path, data.files, cfg['path'])
    await asyncio.to_thread(run_single_refresh, cfg['url'], cfg['token'], data.media_id)
    return {"logs": logs}

@app.post("/api/media/rename")
async def rename_files(data: RenameModel):
    cfg = load_config()
    logs = await asyncio.to_thread(execute_folder_rename, cfg['url'], cfg['token'], data.folder_path)
    await asyncio.to_thread(run_single_refresh, cfg['url'], cfg['token'], data.media_id)
    return {"logs": logs}

@app.post("/api/media/purge")
async def purge_directory(data: PurgeModel):
    cfg = load_config()
    logs = await asyncio.to_thread(execute_directory_purge, cfg['url'], cfg['token'], data.folder_path, data.media_id, data.season_key, cfg['path'])
    return {"logs": logs}

@app.post("/api/media/upload")
async def upload_files(media_id: int = Form(...), folder_path: str = Form(...), files: List[UploadFile] = File(...)):
    cfg = load_config()
    logger.info(f"📤 Uploading {len(files)} files to: {folder_path}")
    files_data = {}
    for file in files: content = await file.read(); files_data[file.filename] = content
    logs = await asyncio.to_thread(execute_folder_upload, cfg['url'], cfg['token'], folder_path, files_data)
    await asyncio.to_thread(run_single_refresh, cfg['url'], cfg['token'], media_id)
    return {"logs": logs}

@app.post("/api/sync/stop")
async def stop_sync():
    logger.info("🛑 Sync stop requested by user")
    RcloneHandler.kill_sync_process()
    state.sync_running = False
    cfg = load_config(); cfg['last_sync_ts'] = time.time(); save_config(cfg)
    return {"status": "stopped_and_reset"}

@app.websocket("/ws/sync")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "update", "running": state.sync_running, "data": state.sync_data, "files": state.active_files})
    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                if msg == "start_sync" and not state.sync_running: asyncio.create_task(perform_rclone_sync())
            except asyncio.TimeoutError: pass 
            await websocket.send_json({"type": "update", "running": state.sync_running, "data": state.sync_data, "files": state.active_files})
    except: pass
    
app.mount("/", StaticFiles(directory="static", html=True), name="static")
