import streamlit as st
import json
import os
import threading
import time
from database import get_all_media, get_subtitles, clear_db
from logic import run_library_scan, run_single_refresh

# 設定路徑
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

# 頁面設定 (Wide mode)
st.set_page_config(page_title="Subana", page_icon="🎬", layout="wide")

# --- CSS 優化 (現代化深色風格) ---
st.markdown("""
<style>
    /* 調整主標題邊距 */
    .block-container { padding-top: 2rem; }
    
    /* 側邊欄樣式 */
    section[data-testid="stSidebar"] {
        background-color: #1e1e1e;
    }
    
    /* Log 區塊樣式 (終端機風格) */
    .log-container {
        background-color: #0d1117;
        color: #58a6ff;
        font-family: 'JetBrains Mono', 'Consolas', monospace;
        font-size: 0.8rem;
        padding: 15px;
        border-radius: 8px;
        border: 1px solid #30363d;
        height: 200px;
        overflow-y: auto;
        white-space: pre-wrap;
        box-shadow: inset 0 0 10px rgba(0,0,0,0.5);
    }

    /* 列表卡片樣式 */
    .element-container button { width: 100%; }
    div[data-testid="stExpander"] {
        border: 1px solid #444;
        border-radius: 8px;
        background-color: #262730;
    }
    
    /* 字幕詳情文字 */
    .sub-info {
        background-color: #111;
        color: #eee;
        padding: 12px;
        border-radius: 6px;
        font-family: monospace;
        font-size: 0.85em;
        line-height: 1.5;
        border-left: 4px solid #ff4b4b;
    }
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

def tail_log(lines=30):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                return "".join(f.readlines()[-lines:])
        except: return "讀取日誌失敗..."
    return "尚無日誌..."

# --- 彈出視窗 ---
@st.dialog("詳細資訊")
def show_details(item_name, media_id):
    st.header(f"🎬 {item_name}")
    st.divider()
    subs = get_subtitles(media_id)
    if not subs:
        st.warning("⚠️ 此項目尚無內嵌字幕分析資料")
    else:
        for s in subs:
            with st.expander(f"📁 {s['season']}", expanded=True):
                st.markdown(f"<div class='sub-info'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# ==========================================
# 側邊欄 (Sidebar) - 設定與標題
# ==========================================
config = load_config()

with st.sidebar:
    # 標題區
    st.title("🎬 Subana")
    st.caption("媒體庫字幕管理系統 v6.5")
    st.divider()

    # 連線狀態指示
    if config.get('url') and config.get('token'):
        st.success("🟢 設定已就緒")
    else:
        st.error("🔴 請先完成設定")

    # 設定表單
    with st.expander("⚙️ 連線與路徑設定", expanded=True):
        with st.form("sidebar_config"):
            new_url = st.text_input("Alist URL", value=config.get("url", ""))
            new_token = st.text_input("Token", value=config.get("token", ""), type="password")
            new_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
            
            if st.form_submit_button("💾 儲存設定"):
                config['url'] = new_url.rstrip('/')
                config['token'] = new_token
                config['path'] = new_path
                save_config(config)
                st.toast("設定已儲存！")
                time.sleep(0.5)
                st.rerun()

    # 掃描操作區
    st.divider()
    st.subheader("🛠️ 維護操作")
    
    if st.button("🚀 開始全域掃描", type="primary", use_container_width=True):
        if not config.get('url') or not config.get('token'):
            st.error("設定不完整")
        else:
            st.toast("背景掃描已啟動...")
            open(LOG_FILE, 'w').close() # 清空舊 Log
            threading.Thread(target=run_library_scan, 
                             args=(config['url'], config['token'], config['path'])).start()
    
    if st.button("🗑️ 清空資料庫", use_container_width=True):
        clear_db()
        st.toast("資料庫已重置")
        time.sleep(1)
        st.rerun()

# ==========================================
# 主畫面 (Main Content)
# ==========================================

# 🔥 Log 區塊 (置頂 + 局部刷新)
@st.fragment(run_every=1)
def log_section():
    with st.expander("📜 系統執行日誌 (Real-time Monitor)", expanded=True):
        log_content = tail_log(20)
        # 使用 Markdown 模擬終端機樣式
        st.markdown(f'<div class="log-container">{log_content}</div>', unsafe_allow_html=True)
        
        col_l1, col_l2 = st.columns([6, 1])
        if col_l2.button("清除 Log", key="clear_log_btn"):
            open(LOG_FILE, 'w').close()

log_section()

st.divider()

# 媒體列表區塊
col_filter1, col_filter2, col_refresh = st.columns([1, 2, 1])
filter_type = col_filter1.selectbox("📂 類型篩選", ["All", "Movie", "TV"])
search_query = col_filter2.text_input("🔍 搜尋媒體", placeholder="輸入關鍵字 (例如: Inception)...")

if col_refresh.button("🔄 重新整理列表", use_container_width=True):
    st.rerun()

# 獲取資料
rows = get_all_media(filter_type, search_query)

if not rows:
    st.info("👋 資料庫目前是空的。請在左側側邊欄點擊 **「🚀 開始全域掃描」**。")
else:
    st.write(f"📚 共找到 **{len(rows)}** 個項目")
    
    # --- 卡片式列表渲染 ---
    for row in rows:
        # 使用 container 加上 border 形成卡片效果
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([0.5, 0.5, 4, 1, 1], vertical_alignment="center")
            
            # Drive ID
            c1.caption(f"Drive {row['drive_id']}")
            
            # Type Badge
            if row['type'] == 'movie':
                c2.markdown("🎬 **電影**")
            else:
                c2.markdown("📺 **影集**")
            
            # Name
            c3.markdown(f"**{row['name']}**")
            
            # Action Buttons
            if c4.button("🔄 更新", key=f"ref_{row['id']}", use_container_width=True):
                st.toast(f"正在更新: {row['name']}...")
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            if c5.button("ℹ️ 詳細", key=f"det_{row['id']}", use_container_width=True):
                show_details(row['name'], row['id'])
