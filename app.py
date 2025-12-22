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

# --- iOS 16 風格 CSS (自動適配淺色/深色) ---
st.markdown("""
<style>
    /* === 1. 定義顏色變數 (自動適配系統設定) === */
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-color: #000000;
            --card-bg: rgba(28, 28, 30, 0.7);
            --text-color: #FFFFFF;
            --sub-text: #8E8E93;
            --border-color: rgba(255, 255, 255, 0.1);
            --log-bg: #1C1C1E;
            --log-text: #D0D0D0;
            --btn-bg: rgba(255, 255, 255, 0.1);
            --btn-hover: rgba(255, 255, 255, 0.2);
        }
    }
    @media (prefers-color-scheme: light) {
        :root {
            --bg-color: #F2F2F7;
            --card-bg: rgba(255, 255, 255, 0.7);
            --text-color: #000000;
            --sub-text: #6C6C70;
            --border-color: rgba(0, 0, 0, 0.05);
            --log-bg: #FFFFFF;
            --log-text: #333333;
            --btn-bg: #FFFFFF;
            --btn-hover: #F2F2F7;
        }
    }

    /* === 2. 全域設定 === */
    .stApp {
        background-color: var(--bg-color);
        color: var(--text-color);
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 隱藏預設 Header 與 Footer */
    header { visibility: hidden; }
    footer { visibility: hidden; }
    .block-container { padding-top: 2rem; padding-bottom: 4rem; }

    /* === 3. 側邊欄 (Sidebar) === */
    section[data-testid="stSidebar"] {
        background-color: var(--card-bg);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-right: 1px solid var(--border-color);
    }

    /* === 4. 卡片容器 (Glassmorphism) === */
    div[data-testid="stExpander"], div[data-testid="stContainer"] {
        background-color: var(--card-bg);
        border: 1px solid var(--border-color);
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.02); /* 極淡的陰影 */
        backdrop-filter: blur(10px);
    }
    
    /* 修正 Container 內部的邊距 */
    div[data-testid="stContainer"] > div {
        padding: 10px 0;
    }

    /* === 5. 按鈕 (Modern Rectangles) === */
    .stButton button {
        border-radius: 8px !important; /* 不用膠囊，改為微圓角 */
        border: 1px solid var(--border-color);
        background-color: var(--btn-bg);
        color: var(--text-color);
        font-weight: 500;
        padding: 0.4rem 1rem;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .stButton button:hover {
        background-color: var(--btn-hover);
        border-color: var(--sub-text);
        transform: translateY(-1px);
    }
    
    /* Primary 按鈕 (例如開始掃描) */
    button[kind="primary"] {
        background-color: var(--text-color) !important;
        color: var(--bg-color) !important;
        border: none;
    }

    /* === 6. 輸入框 === */
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
        background-color: var(--btn-bg);
        color: var(--text-color);
        border: 1px solid var(--border-color);
        border-radius: 8px;
    }

    /* === 7. 現代化 Log 區塊 === */
    .log-box {
        font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
        font-size: 12px;
        background-color: var(--log-bg);
        color: var(--log-text);
        padding: 15px;
        border-radius: 8px;
        height: 200px;
        overflow-y: auto;
        line-height: 1.6;
        border: 1px solid var(--border-color);
        box-shadow: inset 0 1px 4px rgba(0,0,0,0.05);
    }
    /* Log 內的 Timestamp 顏色 */
    .log-time { color: var(--sub-text); margin-right: 8px; user-select: none; }

    /* === 8. 其他細節 === */
    hr { border-color: var(--border-color); }
    
    /* 狀態標籤 */
    .badge {
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-movie { background-color: rgba(52, 199, 89, 0.15); color: #34C759; } /* iOS Green */
    .badge-tv { background-color: rgba(0, 122, 255, 0.15); color: #007AFF; } /* iOS Blue */

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
                content = f.readlines()[-lines:]
                # 簡單的 Log 格式化，讓它更好看
                formatted = []
                for line in content:
                    # 假設 Log 格式是: TIMESTAMP [LEVEL] MESSAGE
                    # 這裡只做簡單的 HTML 轉義防止 XSS
                    safe_line = line.replace("<", "&lt;").replace(">", "&gt;")
                    formatted.append(f"<div>{safe_line}</div>")
                return "".join(formatted)
        except: return "讀取日誌失敗..."
    return "系統待機中..."

# --- 彈出視窗 ---
@st.dialog("媒體詳細資訊")
def show_details(item_name, media_id):
    st.caption("MEDIA DETAILS")
    st.markdown(f"### {item_name}")
    st.divider()
    
    subs = get_subtitles(media_id)
    if not subs:
        st.info("尚無內嵌字幕資料")
    else:
        for s in subs:
            with st.expander(f"{s['season']}", expanded=True):
                # 使用 code block 呈現，保持 monospaced 字體
                st.code(s['subtitle_tracks'], language="text")

# ==========================================
# 側邊欄 (Sidebar)
# ==========================================
config = load_config()

with st.sidebar:
    st.markdown("## Subana")
    
    # 簡約的狀態顯示
    if config.get('url') and config.get('token'):
        st.markdown("<span style='color:#30D158; font-size:0.8rem;'>● Online</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span style='color:#FF453A; font-size:0.8rem;'>● Offline (Setup Required)</span>", unsafe_allow_html=True)
    
    st.markdown("---")

    # 設定區
    with st.expander("連線設定 (Settings)", expanded=False):
        with st.form("sidebar_config"):
            new_url = st.text_input("Alist URL", value=config.get("url", ""))
            new_token = st.text_input("Token", value=config.get("token", ""), type="password")
            new_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
            
            if st.form_submit_button("儲存變更"):
                config['url'] = new_url.rstrip('/')
                config['token'] = new_token
                config['path'] = new_path
                save_config(config)
                st.toast("設定已儲存")
                time.sleep(0.5)
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    
    # 功能按鈕
    if st.button("掃描媒體庫", type="primary", use_container_width=True):
        if not config.get('url'):
            st.error("請先設定 URL")
        else:
            st.toast("開始掃描...")
            open(LOG_FILE, 'w').close()
            threading.Thread(target=run_library_scan, 
                             args=(config['url'], config['token'], config['path'])).start()
    
    if st.button("清空資料庫", type="secondary", use_container_width=True):
        clear_db()
        st.toast("資料庫已清空")
        time.sleep(1)
        st.rerun()

# ==========================================
# 主畫面 (Main)
# ==========================================

# 🔥 Log 區塊 (保持置頂，使用現代化樣式)
@st.fragment(run_every=1)
def log_section():
    with st.expander("System Console", expanded=True):
        log_html = tail_log(20)
        # 注入 HTML 讓 Log 樣式生效
        st.markdown(f'<div class="log-box">{log_html}</div>', unsafe_allow_html=True)
        
        col_r1, col_r2 = st.columns([8, 1])
        if col_r2.button("清除", key="cls_btn"):
            open(LOG_FILE, 'w').close()

log_section()

st.markdown("### Library")

# 篩選器
col_filter, col_search, col_refresh = st.columns([1.5, 4, 1])
with col_filter:
    filter_type = st.selectbox("類型", ["All", "Movie", "TV"], label_visibility="collapsed")
with col_search:
    search_query = st.text_input("搜尋", placeholder="搜尋...", label_visibility="collapsed")
with col_refresh:
    if st.button("⟳", help="重新整理", use_container_width=True):
        st.rerun()

# 列表呈現
rows = get_all_media(filter_type, search_query)

if not rows:
    st.markdown("""
        <div style="text-align:center; padding: 40px; color: #888;">
            無資料<br>請點擊側邊欄的「掃描媒體庫」
        </div>
    """, unsafe_allow_html=True)
else:
    st.caption(f"共 {len(rows)} 個項目")
    
    for row in rows:
        # 使用原生 container 並透過 CSS 美化
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([0.5, 4, 1, 1, 1], vertical_alignment="center")
            
            # Badge
            if row['type'] == 'movie':
                c1.markdown('<span class="badge badge-movie">MOV</span>', unsafe_allow_html=True)
            else:
                c1.markdown('<span class="badge badge-tv">TV</span>', unsafe_allow_html=True)
            
            # Name
            c2.markdown(f"**{row['name']}**")
            
            # Drive
            c3.caption(f"Drive {row['drive_id']}")
            
            # Actions (Minimalist Buttons)
            if c4.button("更新", key=f"upd_{row['id']}", use_container_width=True):
                st.toast(f"正在更新: {row['name']}")
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            # Primary action usually on the right
            if c5.button("詳細", key=f"det_{row['id']}", type="secondary", use_container_width=True):
                show_details(row['name'], row['id'])
