import streamlit as st
import json
import os
import threading
import time
from database import get_all_media, get_subtitles, clear_db
from logic import run_library_scan, run_single_refresh # 引入新函式

# 設定
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

st.set_page_config(page_title="Subana 媒體庫", page_icon="🎬", layout="wide")

st.markdown("""
<style>
    .stButton button { width: 100%; }
    .sub-info { background-color: #262730; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; font-size: 0.85em; }
    .log-box { font-family: 'Consolas', monospace !important; }
</style>
""", unsafe_allow_html=True)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try: with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def tail_log(lines=10):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                return "".join(f.readlines()[-lines:])
        except: return "Error reading log..."
    return "No logs..."

@st.dialog("字幕詳細資訊")
def show_details(item_name, media_id):
    st.subheader(f"🎬 {item_name}")
    subs = get_subtitles(media_id)
    if not subs: st.warning("尚無分析資料")
    for s in subs:
        with st.expander(f"{s['season']}", expanded=True):
            st.markdown(f"<div class='sub-info'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

st.title("🎬 Subana 媒體庫管理")

# Log Fragment
@st.fragment(run_every=1)
def log_section():
    with st.expander("📜 即時系統日誌", expanded=True):
        c1, c2 = st.columns([6, 1])
        c1.code(tail_log(10), language="text")
        if c2.button("🗑️ 清空"): open(LOG_FILE, 'w').close(); st.rerun()
log_section()

tab1, tab2 = st.tabs(["📚 媒體列表", "⚙️ 設定與掃描"])

# === Tab 1: 列表 (新增刷新按鈕) ===
with tab1:
    c1, c2, c3 = st.columns([1, 2, 1])
    f_type = c1.selectbox("類型", ["All", "Movie", "TV"])
    f_query = c2.text_input("搜尋", placeholder="關鍵字...")
    if c3.button("🔄 重新整理介面"): st.rerun()

    rows = get_all_media(f_type, f_query)
    
    st.markdown("---")
    # 調整欄位比例：[1, 1, 3, 1, 1]
    h1, h2, h3, h4, h5 = st.columns([1, 1, 3, 1, 1])
    h1.markdown("**Drive**")
    h2.markdown("**Type**")
    h3.markdown("**Name**")
    h4.markdown("**Refresh**") # 新增
    h5.markdown("**Detail**")
    st.markdown("---")

    config = load_config() # 讀取設定以獲取 URL/Token

    for row in rows:
        c1, c2, c3, c4, c5 = st.columns([1, 1, 3, 1, 1])
        c1.text(row['drive_id'])
        c2.text("🎬 電影" if row['type'] == 'movie' else "📺 影集")
        c3.text(row['name'])
        
        # 🔥 按鈕 1: 刷新單一項目
        if c4.button("🔄 更新", key=f"ref_{row['id']}"):
            if not config.get('url'): st.error("請先設定 URL")
            else:
                st.toast(f"正在更新: {row['name']}")
                # 這裡使用 threading 避免介面卡住
                t = threading.Thread(target=run_single_refresh, 
                                     args=(config['url'], config['token'], row['id']))
                t.start()
        
        # 🔥 按鈕 2: 詳細資訊
        if c5.button("ℹ️ 詳細", key=f"det_{row['id']}"):
            show_details(row['name'], row['id'])

# === Tab 2: 設定 ===
with tab2:
    with st.form("settings"):
        st.subheader("連線設定")
        n_url = st.text_input("Alist URL", value=config.get("url", ""))
        n_token = st.text_input("Token", value=config.get("token", ""), type="password")
        n_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
        if st.form_submit_button("💾 儲存"):
            config.update({"url": n_url.rstrip('/'), "token": n_token, "path": n_path})
            save_config(config)
            st.success("已儲存")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("🚀 開始全域掃描 (跳過已存在)", type="primary"):
        st.toast("掃描啟動...")
        open(LOG_FILE, 'w').close()
        threading.Thread(target=run_library_scan, args=(n_url, n_token, n_path)).start()
        
    if c2.button("🗑️ 清空資料庫"):
        clear_db()
        st.warning("已清空")
        time.sleep(1)
        st.rerun()
