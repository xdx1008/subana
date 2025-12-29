import sqlite3
import json
import os

DB_FILE = '/app/data/media.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists('/app/data'):
        os.makedirs('/app/data')
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            drive_id TEXT NOT NULL,
            name TEXT NOT NULL,
            full_path TEXT UNIQUE NOT NULL,
            all_subs TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_media(m_type, drive_id, name, full_path, all_subs):
    conn = get_db_connection()
    # 檢查是否存在
    cur = conn.execute("SELECT id FROM media WHERE full_path = ?", (full_path,))
    row = cur.fetchone()
    
    subs_json = json.dumps(all_subs)
    
    if row:
        conn.execute("UPDATE media SET all_subs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (subs_json, row['id']))
    else:
        conn.execute("INSERT INTO media (type, drive_id, name, full_path, all_subs) VALUES (?, ?, ?, ?, ?)",
                     (m_type, drive_id, name, full_path, subs_json))
    conn.commit()
    conn.close()

def get_all_media(filter_type="All", search_term=""):
    conn = get_db_connection()
    query = "SELECT * FROM media WHERE 1=1"
    params = []
    
    if filter_type != "All":
        query += " AND type = ?"
        params.append(filter_type.lower())
        
    if search_term:
        query += " AND name LIKE ?"
        params.append(f"%{search_term}%")
        
    query += " ORDER BY name ASC"
    
    cur = conn.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_media_by_id(media_id):
    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,))
    row = cur.fetchone()
    conn.close()
    return row

# 🔥 [v26.2 新增] 根據路徑獲取媒體資訊 (用於比對季數)
def get_media_by_path(full_path):
    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM media WHERE full_path = ?", (full_path,))
    row = cur.fetchone()
    conn.close()
    return row

def get_subtitles(media_id):
    row = get_media_by_id(media_id)
    if row and row['all_subs']:
        return json.loads(row['all_subs'])
    return []

def check_media_exists(full_path):
    conn = get_db_connection()
    cur = conn.execute("SELECT id FROM media WHERE full_path = ?", (full_path,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists

def clear_db():
    conn = get_db_connection()
    conn.execute("DELETE FROM media")
    conn.commit()
    conn.close()

def delete_season_data(media_id, season_name):
    conn = get_db_connection()
    try:
        cur = conn.execute("SELECT type, all_subs FROM media WHERE id = ?", (media_id,))
        row = cur.fetchone()
        if not row or not row['all_subs']: return

        current_data = json.loads(row['all_subs'])
        
        if row['type'] == 'movie' and season_name == 'Movie':
            conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
        else:
            new_data = [s for s in current_data if s.get('season') != season_name]
            conn.execute("UPDATE media SET all_subs = ? WHERE id = ?", (json.dumps(new_data), media_id))
        
        conn.commit()
    except Exception as e:
        print(f"DB Delete Error: {e}")
    finally:
        conn.close()

# 初始化
init_db()
