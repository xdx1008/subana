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
    .sub-info { background-color: #262730; padding: 10px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; font-size: 0.85em; }
    /* 強制 Log 區塊樣式 */
    .stCode { font-family: 'Consolas', 'Courier New', monospace !important; }
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

def tail_log(lines=10):
    """只讀取最後 N 行"""
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                return "".join(content[-lines:]) # 取最後 lines 行
        except: return "讀取日誌失敗..."
    return "尚無日誌..."

# --- 彈出視窗 ---
@st.dialog("字幕詳細資訊")
def show_details(item_name, media_id):
    st.subheader(f"🎬 {item_name}")
    subs = get_subtitles(media_id)
    if not subs: st.warning("尚無分析資料")
    for s in subs:
        with st.expander(f"{s['season']}", expanded=True):
            st.markdown(f"<div class='sub-info'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# --- 主介面 ---
st.title("🎬 Subana 媒體庫管理")

# 🔥 Log 區塊 (使用 Fragment 實現局部刷新)
# run_every=1 代表這個函式內的元件每 1 秒會自動重繪一次，但不影響外部
@st.fragment(run_every=1)
def log_section():
    with st.expander("📜 即時系統日誌 (Real-time Log)", expanded=True):
        col_log1, col_log2 = st.columns([6, 1])
        
        # 讀取 Log 內容 (限制 10 行)
        log_content = tail_log(10)
        
        # 顯示 Log (使用 st.code 保持格式)
        col_log1.code(log_content, language="text")
        
        if col_log2.button("🗑️ 清空"):
            open(LOG_FILE, 'w').close()
            st.rerun()

# 呼叫 Log 區塊
log_section()

# 分頁
tab1, tab2 = st.tabs(["📚 媒體列表 (Database)", "⚙️ 設定與掃描 (Settings)"])

# === Tab 1: 媒體列表 ===
with tab1:
    col1, col2, col3 = st.columns([1, 2, 1])
    filter_type = col1.selectbox("類型篩選", ["All", "Movie", "TV"])
    search_query = col2.text_input("搜尋名稱", placeholder="輸入關鍵字...")
    if col3.button("🔄 重新整理列表"): st.rerun()

    rows = get_all_media(filter_type, search_query)
    
    st.markdown("---")
    # 表格標頭
    h1, h2, h3, h4 = st.columns([1, 1, 4, 1])
    h1.markdown("**Drive**")
    h2.markdown("**Type**")
    h3.markdown("**Name**")
    h4.markdown("**Action**")
    st.markdown("---")

    for row in rows:
        c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
        c1.text(row['drive_id'])
        c2.text("🎬 電影" if row['type'] == 'movie' else "📺 影集")
        c3.text(row['name'])
        if c4.button("ℹ️ 詳細", key=f"btn_{row['id']}"):
            show_details(row['name'], row['id'])

    if not rows:
        st.info("資料庫目前為空。請到「設定與掃描」執行掃描任務。")

# === Tab 2: 設定與掃描 ===
with tab2:
    config = load_config()
    
    with st.form("settings_form"):
        st.subheader("連線設定")
        new_url = st.text_input("Alist URL", value=config.get("url", ""))
        new_token = st.text_input("Token", value=config.get("token", ""), type="password")
        new_path = st.text_input("根目錄 (例如 /Cloud)", value=config.get("path", "/Cloud"))
        
        submitted = st.form_submit_button("💾 儲存設定")
        if submitted:
            config['url'] = new_url.rstrip('/')
            config['token'] = new_token
            config['path'] = new_path
            save_config(config)
            st.success("已儲存")

    st.divider()
    
    c1, c2 = st.columns(2)
    if c1.button("🚀 開始全域掃描 (建立資料庫)", type="primary"):
        if not new_url or not new_token:
            st.error("請先填寫設定")
        else:
            st.toast("掃描任務已啟動，請查看上方日誌...")
            # 清空舊 Log
            open(LOG_FILE, 'w').close()
            t = threading.Thread(target=run_library_scan, args=(new_url, new_token, new_path))
            t.start()
            # 這裡不需要 sleep 或 rerun，因為上方的 fragment 會自動抓到新 Log
            
    if c2.button("🗑️ 清空資料庫 (重置)"):
        clear_db()
        st.warning("資料庫已清空")
        time.sleep(1)
        st.rerun()
