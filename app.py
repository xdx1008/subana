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
st.set_page_config(page_title="Subana", page_icon="", layout="wide")

# --- iOS 風格 CSS 注入 ---
st.markdown("""
<style>
    /* 全域字體與背景 - 模擬 iOS Dark Mode */
    .stApp {
        background-color: #000000;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* 側邊欄 (Sidebar) - 磨砂玻璃感深灰 */
    section[data-testid="stSidebar"] {
        background-color: #1C1C1E; 
        border-right: 1px solid #2C2C2E;
    }
    
    /* 標題與文字 */
    h1, h2, h3 {
        font-weight: 700 !important;
        letter-spacing: -0.5px;
    }
    
    /* 輸入框 (Input Fields) - iOS 風格 */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background-color: #2C2C2E;
        color: white;
        border-radius: 10px;
        border: none;
        padding: 8px 12px;
    }
    .stTextInput input:focus {
        box-shadow: 0 0 0 2px #007AFF; /* iOS Blue Focus */
    }

    /* 按鈕 (Buttons) - 膠囊與圓角 */
    .stButton button {
        border-radius: 12px;
        font-weight: 600;
        border: none;
        padding: 0.5rem 1rem;
        transition: all 0.2s ease;
    }
    
    /* 主要按鈕 (Primary) - iOS Blue */
    button[kind="primary"] {
        background-color: #007AFF !important;
        color: white !important;
    }
    button[kind="primary"]:hover {
        background-color: #0062CC !important;
    }

    /* 次要按鈕 (Secondary) - 深灰底藍字 */
    button[kind="secondary"] {
        background-color: #3A3A3C !important;
        color: #0A84FF !important;
    }
    button[kind="secondary"]:hover {
        background-color: #48484A !important;
    }

    /* 刪除類按鈕 (特定 key 偵測不易，需手動 CSS class，這裡通用處理) */
    /* 列表卡片 (Card) - 模擬 iOS TableView Cell */
    div[data-testid="stContainer"] {
        /* 這裡只影響有 border 的 container */
    }
    
    /* 自定義卡片容器樣式 */
    .ios-card {
        background-color: #1C1C1E;
        padding: 16px;
        border-radius: 14px;
        margin-bottom: 12px;
        /* box-shadow: 0 2px 6px rgba(0,0,0,0.2); 移除陰影更扁平化 */ 
    }

    /* Log 區塊 - Xcode Console 風格 */
    .log-box {
        font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
        font-size: 11px;
        background-color: #121212;
        color: #30D158; /* iOS Green */
        padding: 12px;
        border-radius: 10px;
        height: 180px;
        overflow-y: auto;
        line-height: 1.4;
        border: 1px solid #333;
    }

    /* 隱藏預設 Header */
    header { visibility: hidden; }
    .block-container { padding-top: 2rem; padding-bottom: 5rem; }
    
    /* 彈出視窗內的文字 */
    .sub-info {
        background-color: #2C2C2E;
        color: #E5E5EA;
        padding: 12px;
        border-radius: 8px;
        font-family: monospace;
        font-size: 0.9em;
        line-height: 1.5;
        border-left: 3px solid #007AFF;
    }
    
    /* 分頁 Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 20px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 20px;
        color: #8E8E93;
        font-weight: 600;
        border: none !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3A3A3C;
        color: #FFFFFF !important;
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
    return "系統待機中..."

# --- 彈出視窗 ---
@st.dialog("媒體詳細資訊")
def show_details(item_name, media_id):
    st.markdown(f"### {item_name}")
    subs = get_subtitles(media_id)
    if not subs:
        st.warning("⚠️ 尚無內嵌字幕資料")
    else:
        for s in subs:
            with st.expander(f"📂 {s['season']}", expanded=True):
                st.markdown(f"<div class='sub-info'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# ==========================================
# 側邊欄 (控制中心)
# ==========================================
config = load_config()

with st.sidebar:
    st.markdown("##  Subana")
    st.caption("Media Library Manager")
    st.markdown("---")

    # 狀態卡片
    if config.get('url') and config.get('token'):
        st.success("連線正常 (Connected)")
    else:
        st.error("未設定連線")

    with st.expander("⚙️ 設定 (Settings)", expanded=True):
        with st.form("sidebar_config"):
            new_url = st.text_input("Alist URL", value=config.get("url", ""))
            new_token = st.text_input("Token", value=config.get("token", ""), type="password")
            new_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
            
            if st.form_submit_button("儲存 (Save)"):
                config['url'] = new_url.rstrip('/')
                config['token'] = new_token
                config['path'] = new_path
                save_config(config)
                st.toast("設定已更新", icon="✅")
                time.sleep(0.5)
                st.rerun()

    st.markdown("### 操作 (Actions)")
    
    col_act1, col_act2 = st.columns(2)
    if col_act1.button("🚀 掃描", type="primary", use_container_width=True):
        if not config.get('url') or not config.get('token'):
            st.error("設定不全")
        else:
            st.toast("背景掃描啟動...", icon="⏳")
            open(LOG_FILE, 'w').close()
            threading.Thread(target=run_library_scan, 
                             args=(config['url'], config['token'], config['path'])).start()
    
    if col_act2.button("🗑️ 清除", type="secondary", use_container_width=True):
        clear_db()
        st.toast("資料庫已重置", icon="🗑️")
        time.sleep(1)
        st.rerun()

# ==========================================
# 主畫面 (內容呈現)
# ==========================================

# 🔥 Log 區塊 (置頂監控)
@st.fragment(run_every=1)
def log_section():
    # 這裡使用 expander 收納，保持簡約
    with st.expander("CONSOLE LOG", expanded=True):
        log_content = tail_log(30)
        st.markdown(f'<div class="log-box">{log_content}</div>', unsafe_allow_html=True)
        
        c1, c2 = st.columns([8, 1])
        if c2.button("CLS", help="清除 Log", key="cls_btn"):
            open(LOG_FILE, 'w').close()

log_section()

st.markdown("### Library")

# 篩選工具列
col_filter, col_search, col_refresh = st.columns([1.5, 3, 1])
with col_filter:
    filter_type = st.selectbox("類別", ["All", "Movie", "TV"], label_visibility="collapsed")
with col_search:
    search_query = st.text_input("搜尋", placeholder="搜尋電影或劇集名稱...", label_visibility="collapsed")
with col_refresh:
    if st.button("🔄", help="重新整理列表", use_container_width=True):
        st.rerun()

# 獲取資料
rows = get_all_media(filter_type, search_query)

if not rows:
    st.info("資料庫是空的。請在左側側邊欄點擊「🚀 掃描」。")
else:
    # --- 列表渲染 (iOS Card Style) ---
    st.markdown(f"<div style='color: gray; font-size: 0.8em; margin-bottom: 10px; margin-left: 5px;'>{len(rows)} 項目</div>", unsafe_allow_html=True)
    
    for row in rows:
        # 使用自訂的 border=False 容器，利用 CSS .stContainer 來美化 (Streamlit 原生 border 比較醜)
        # 這裡改用原生的 container(border=True) 但透過上面的 CSS 調整了顏色
        with st.container(border=True):
            # 佈局: Icon | Name | Drive | Actions
            c1, c2, c3, c4, c5 = st.columns([0.4, 4, 0.8, 1, 1], vertical_alignment="center")
            
            # Icon
            if row['type'] == 'movie':
                c1.markdown("🎬")
            else:
                c1.markdown("📺")
            
            # Name
            c2.markdown(f"**{row['name']}**")
            
            # Drive Tag
            c3.caption(f"Drive {row['drive_id']}")
            
            # Actions
            if c4.button("更新", key=f"upd_{row['id']}", use_container_width=True):
                st.toast(f"更新中: {row['name']}")
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            # Primary style for Detail
            if c5.button("詳細", key=f"det_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])
