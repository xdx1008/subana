import sqlite3
import json
import os
import logging

DB_FILE = '/app/data/media.db'

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists('/app/data'):
        os.makedirs('/app/data')
    
    with get_db_connection() as conn:
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

def save_media(m_type, drive_id, name, full_path, all_subs):
    subs_json = json.dumps(all_subs)
    try:
        with get_db_connection() as conn:
            cur = conn.execute("SELECT id FROM media WHERE full_path = ?", (full_path,))
            row = cur.fetchone()
            
            if row:
                conn.execute("UPDATE media SET all_subs = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (subs_json, row['id']))
            else:
                conn.execute("INSERT INTO media (type, drive_id, name, full_path, all_subs) VALUES (?, ?, ?, ?, ?)",
                             (m_type, drive_id, name, full_path, subs_json))
    except Exception as e:
        logging.error(f"DB Save Error: {e}")

def get_all_media(filter_type="All", search_term=""):
    query = "SELECT * FROM media WHERE 1=1"
    params = []
    
    if filter_type != "All":
        query += " AND type = ?"
        params.append(filter_type.lower())
        
    if search_term:
        query += " AND name LIKE ?"
        params.append(f"%{search_term}%")
        
    query += " ORDER BY name ASC"
    
    with get_db_connection() as conn:
        cur = conn.execute(query, params)
        return cur.fetchall()

def get_media_by_id(media_id):
    with get_db_connection() as conn:
        cur = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,))
        return cur.fetchone()

def get_media_by_path(full_path):
    with get_db_connection() as conn:
        cur = conn.execute("SELECT * FROM media WHERE full_path = ?", (full_path,))
        return cur.fetchone()

def get_subtitles(media_id):
    row = get_media_by_id(media_id)
    if row and row['all_subs']:
        return json.loads(row['all_subs'])
    return []

def check_media_exists(full_path):
    with get_db_connection() as conn:
        cur = conn.execute("SELECT id FROM media WHERE full_path = ?", (full_path,))
        return cur.fetchone() is not None

def clear_db():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM media")

def delete_season_data(media_id, season_name):
    try:
        with get_db_connection() as conn:
            cur = conn.execute("SELECT type, all_subs FROM media WHERE id = ?", (media_id,))
            row = cur.fetchone()
            if not row or not row['all_subs']: return

            current_data = json.loads(row['all_subs'])
            
            if row['type'] == 'movie' and season_name == 'Movie':
                conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
            else:
                new_data = [s for s in current_data if s.get('season') != season_name]
                conn.execute("UPDATE media SET all_subs = ? WHERE id = ?", (json.dumps(new_data), media_id))
    except Exception as e:
        logging.error(f"DB Delete Error: {e}")

# 初始化
init_db()