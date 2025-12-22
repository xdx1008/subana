import sqlite3
import os
import threading

DB_FILE = '/app/data/media.db'
lock = threading.Lock()

def init_db():
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                drive_id TEXT,
                name TEXT,
                full_path TEXT UNIQUE,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS subtitles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id INTEGER,
                season TEXT,
                audio_tracks TEXT,
                subtitle_tracks TEXT,
                FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
        conn.close()

def save_media(m_type, drive_id, name, full_path, sub_data):
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        try:
            c.execute("DELETE FROM media WHERE full_path = ?", (full_path,))
            c.execute("INSERT INTO media (type, drive_id, name, full_path) VALUES (?, ?, ?, ?)",
                      (m_type, drive_id, name, full_path))
            media_id = c.lastrowid
            
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
    
    # 🔥 修改查詢：串聯 subtitles 表的資訊，以便在列表判斷語言
    query = """
        SELECT m.*, GROUP_CONCAT(s.subtitle_tracks, ' ') as all_subs 
        FROM media m 
        LEFT JOIN subtitles s ON m.id = s.media_id
        WHERE 1=1 
    """
    params = []
    
    if filter_type and filter_type != "All":
        query += " AND m.type = ?"
        params.append(filter_type.lower())
        
    if search_query:
        query += " AND m.name LIKE ?"
        params.append(f"%{search_query}%")
        
    query += " GROUP BY m.id ORDER BY m.drive_id ASC, m.name ASC"
    
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

def check_media_exists(full_path):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM media WHERE full_path = ?", (full_path,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def get_media_by_id(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM media WHERE id = ?", (media_id,))
    row = c.fetchone()
    conn.close()
    return row

def clear_db():
    with lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM media")
        c.execute("DELETE FROM subtitles")
        conn.commit()
        conn.close()

if not os.path.exists('/app/data'): os.makedirs('/app/data')
init_db()
