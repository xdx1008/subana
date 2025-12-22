import streamlit as st
import json
import os
import threading
import time
from database import get_all_media, get_subtitles, clear_db
from logic import run_library_scan

# 設定
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

st.set_page_config(page_title="Subana 媒體庫", page_icon="🎬", layout="wide")

# --- CSS 美化 ---
st.markdown("""
<style>
    .stButton button { width: 100%; }
    .sub-info { background-color: #262730; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; }
</style>
""", unsafe_allow_html=True)

# --- 輔助函式 ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

# --- 彈出視窗 (Dialog) ---
@st.dialog("字幕詳細資訊")
def show_details(item_name, media_id):
    st.subheader(f"🎬 {item_name}")
    subs = get_subtitles(media_id)
    
    if not subs:
        st.warning("尚無分析資料")
    
    for s in subs:
        with st.expander(f"{s['season']}", expanded=True):
            st.markdown(f"<div class='sub-info'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# --- 主介面 ---
st.title("🎬 Subana 媒體庫管理")

tab1, tab2, tab3 = st.tabs(["📚 媒體列表", "⚙️ 設定與掃描", "📜 系統日誌"])

# === Tab 1: 媒體列表 ===
with tab1:
    col1, col2, col3 = st.columns([1, 2, 1])
    filter_type = col1.selectbox("類型篩選", ["All", "Movie", "TV"])
    search_query = col2.text_input("搜尋名稱", placeholder="輸入關鍵字...")
    if col3.button("🔄 重新整理列表"):
        st.rerun()

    # 從 DB 讀取資料
    rows = get_all_media(filter_type, search_query)
    
    # 顯示表頭
    st.markdown("---")
    h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
    h1.markdown("**Drive**")
    h2.markdown("**Type**")
    h3.markdown("**Name**")
    h4.markdown("**Action**")
    st.markdown("---")

    # 顯示資料列
    for row in rows:
        c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
        c1.text(row['drive_id'])
        
        type_badge = "🎬 電影" if row['type'] == 'movie' else "📺 影集"
        c2.text(type_badge)
        
        c3.text(row['name'])
        
        if c4.button("ℹ️ 詳細", key=f"btn_{row['id']}"):
            show_details(row['name'], row['id'])

    if not rows:
        st.info("資料庫為空，請至「設定與掃描」頁面執行掃描。")

# === Tab 2: 設定與掃描 ===
with tab2:
    config = load_config()
    
    with st.expander("連線設定", expanded=True):
        new_url = st.text_input("Alist URL", value=config.get("url", ""))
        new_token = st.text_input("Token", value=config.get("token", ""), type="password")
        new_path = st.text_input("根目錄 (通常是 /Cloud)", value=config.get("path", "/Cloud"))
        
        if st.button("💾 儲存設定"):
            config['url'] = new_url.rstrip('/')
            config['token'] = new_token
            config['path'] = new_path
            save_config(config)
            st.success("已儲存")

    st.divider()
    st.subheader("資料庫操作")
    
    c1, c2 = st.columns(2)
    if c1.button("🚀 開始全域掃描 (建立資料庫)", type="primary"):
        if not new_url or not new_token:
            st.error("請先填寫設定")
        else:
            st.toast("掃描任務已在背景啟動，請稍候...")
            t = threading.Thread(target=run_library_scan, args=(new_url, new_token, new_path))
            t.start()
            
    if c2.button("🗑️ 清空資料庫 (重置)"):
        clear_db()
        st.warning("資料庫已清空")
        time.sleep(1)
        st.rerun()

# === Tab 3: 日誌 ===
with tab3:
    if st.button("刷新日誌"):
        pass
        
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()[-50:]
            st.code("".join(lines))
    else:
        st.text("無日誌")
