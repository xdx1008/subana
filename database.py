import sqlite3
import os
import threading

DB_FILE = '/app/data/media.db'
lock = threading.Lock()

def init_db():
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # 建立媒體主表
        c.execute('''
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,          -- 'movie' or 'tv'
                drive_id TEXT,      -- '01', '02'...
                name TEXT,          -- 資料夾名稱 (e.g. Inception (2010))
                full_path TEXT UNIQUE, -- 完整路徑 (作為唯一識別)
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 建立字幕詳情表 (一對多)
        c.execute('''
            CREATE TABLE IF NOT EXISTS subtitles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id INTEGER,
                season TEXT,        -- 'Movie' or 'Season 01'
                audio_tracks TEXT,  -- 簡略音軌資訊 (選填)
                subtitle_tracks TEXT, -- 詳細字幕資訊 (換行分隔)
                FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        conn.close()

def save_media(m_type, drive_id, name, full_path, sub_data):
    """
    sub_data format: [{'season': 'Season 01', 'subs': 'chi(ass)\neng(srt)'}]
    """
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        try:
            # 1. Insert or Ignore Media (如果路徑已存在則忽略，或可改為 Update)
            # 這裡我們先簡單做: 先刪除舊的 (重掃時更新)，再插入新的
            c.execute("DELETE FROM media WHERE full_path = ?", (full_path,))
            
            c.execute("INSERT INTO media (type, drive_id, name, full_path) VALUES (?, ?, ?, ?)",
                      (m_type, drive_id, name, full_path))
            media_id = c.lastrowid
            
            # 2. Insert Subtitles
            for item in sub_data:
                c.execute("INSERT INTO subtitles (media_id, season, subtitle_tracks) VALUES (?, ?, ?)",
                          (media_id, item['season'], item['subs']))
            
            conn.commit()
        except Exception as e:
            print(f"DB Error: {e}")
        finally:
            conn.close()

def get_all_media(filter_type=None, search_query=None):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = "SELECT * FROM media WHERE 1=1"
    params = []
    
    if filter_type and filter_type != "All":
        query += " AND type = ?"
        params.append(filter_type.lower())
        
    if search_query:
        query += " AND name LIKE ?"
        params.append(f"%{search_query}%")
        
    query += " ORDER BY drive_id ASC, name ASC"
    
    c.execute(query, tuple(params))
    rows = c.fetchall()
    conn.close()
    return rows

def get_subtitles(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM subtitles WHERE media_id = ? ORDER BY season ASC", (media_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def clear_db():
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM media")
        c.execute("DELETE FROM subtitles")
        conn.commit()
        conn.close()

# 初始化
if not os.path.exists('/app/data'): os.makedirs('/app/data')
init_db()
