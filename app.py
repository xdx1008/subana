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

# 頁面設定 (使用通用電影圖示)
st.set_page_config(page_title="Subana", page_icon="🎬", layout="wide")

# --- iOS 現代極簡風格 CSS ---
st.markdown("""
<style>
    /* 全域字體優化 */
    .stApp {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 側邊欄優化 */
    section[data-testid="stSidebar"] {
        background-color: #1c1c1e; /* iOS Dark Gray */
    }
    
    /* 狀態卡片 (Status Card) */
    .status-card {
        background-color: rgba(255,255,255,0.05);
        border-radius: 12px;
        padding: 12px;
        margin-bottom: 15px;
        border: 1px solid rgba(255,255,255,0.1);
    }
    .status-label { font-size: 0.75rem; color: #8e8e93; text-transform: uppercase; letter-spacing: 0.5px; }
    .status-value { font-size: 0.9rem; color: #ffffff; font-weight: 500; word-break: break-all; }
    .status-dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .dot-green { background-color: #30d158; box-shadow: 0 0 8px rgba(48, 209, 88, 0.4); }
    .dot-red { background-color: #ff453a; box-shadow: 0 0 8px rgba(255, 69, 58, 0.4); }

    /* 按鈕樣式重塑 */
    .stButton button {
        border-radius: 10px !important;
        font-weight: 500;
        border: none;
        transition: transform 0.1s;
    }
    .stButton button:active { transform: scale(0.98); }

    /* 列表卡片 */
    div[data-testid="stContainer"] {
        background-color: rgba(255,255,255,0.03);
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.05);
    }

    /* 標籤 (Badges) */
    .type-badge {
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: bold;
        display: inline-block;
        width: 60px;
        text-align: center;
    }
    .tb-movie { background-color: rgba(10, 132, 255, 0.2); color: #0a84ff; border: 1px solid rgba(10, 132, 255, 0.3); }
    .tb-tv { background-color: rgba(48, 209, 88, 0.2); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }

    /* Log 樣式 */
    .log-terminal {
        font-family: 'SF Mono', 'Menlo', monospace;
        font-size: 11px;
        line-height: 1.5;
        background-color: #0d1117;
        color: #c9d1d9;
        padding: 15px;
        border-radius: 8px;
        height: 200px;
        overflow-y: auto;
        border: 1px solid #30363d;
    }
    
    /* 移除頂部空白 */
    .block-container { padding-top: 2rem; }
    
    /* 詳情頁文字 */
    .detail-text {
        font-family: monospace;
        background: rgba(255,255,255,0.05);
        padding: 10px;
        border-radius: 8px;
        font-size: 0.85em;
        color: #eee;
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
        except: return "無法讀取日誌..."
    return "系統待機中..."

@st.dialog("媒體詳情")
def show_details(item_name, media_id):
    st.subheader(f"{item_name}")
    st.markdown("---")
    subs = get_subtitles(media_id)
    if not subs:
        st.warning("⚠️ 此項目尚無內嵌字幕資料")
    else:
        for s in subs:
            with st.expander(f"📁 {s['season']}", expanded=True):
                st.markdown(f"<div class='detail-text'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# ==========================================
# 側邊欄 (Sidebar) - 控制中心
# ==========================================
config = load_config()

with st.sidebar:
    st.title("🎬 Subana")
    st.markdown("---")

    # 1. 狀態儀表板 (永遠顯示)
    # 即使下方的設定收起來，這裡也能看到連線狀態
    is_connected = bool(config.get('url') and config.get('token'))
    
    status_html = f"""
    <div class="status-card">
        <div style="margin-bottom: 8px;">
            <span class="status-dot {'dot-green' if is_connected else 'dot-red'}"></span>
            <span style="color: {'#30d158' if is_connected else '#ff453a'}; font-weight: bold;">
                {'已連線 (Online)' if is_connected else '未設定 (Offline)'}
            </span>
        </div>
        <div class="status-label">TARGET URL</div>
        <div class="status-value">{config.get('url') or '-'}</div>
        <div class="status-label" style="margin-top: 8px;">SCAN ROOT</div>
        <div class="status-value">{config.get('path') or '-'}</div>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)

    # 2. 設定表單 (可收合)
    with st.expander("⚙️ 修改連線設定"):
        with st.form("sidebar_config"):
            new_url = st.text_input("Alist URL", value=config.get("url", ""))
            new_token = st.text_input("Token", value=config.get("token", ""), type="password")
            new_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
            
            if st.form_submit_button("💾 儲存並連線"):
                config['url'] = new_url.rstrip('/')
                config['token'] = new_token
                config['path'] = new_path
                save_config(config)
                st.toast("設定已更新！")
                time.sleep(0.5)
                st.rerun()

    st.markdown("---")
    
    # 3. 快捷操作
    st.markdown("**快速操作**")
    
    if st.button("🚀 開始全域掃描", use_container_width=True):
        if not is_connected:
            st.error("請先完成連線設定")
        else:
            st.toast("正在背景掃描...", icon="⏳")
            open(LOG_FILE, 'w').close()
            threading.Thread(target=run_library_scan, 
                             args=(config['url'], config['token'], config['path'])).start()
    
    if st.button("🗑️ 清空資料庫", use_container_width=True):
        clear_db()
        st.toast("資料庫已清空", icon="🗑️")
        time.sleep(1)
        st.rerun()

# ==========================================
# 主畫面 - 內容展示
# ==========================================

# Log 區塊 (預設收合，不佔空間)
@st.fragment(run_every=1)
def log_section():
    with st.expander("💻 系統終端機 (System Log)", expanded=False):
        log_content = tail_log(20)
        # HTML 渲染終端機風格
        st.markdown(f'<div class="log-terminal">{log_content}</div>', unsafe_allow_html=True)
        
        col_r1, col_r2 = st.columns([8, 1])
        if col_r2.button("清除", key="cls_btn", help="清除目前的日誌內容"):
            open(LOG_FILE, 'w').close()

log_section()

# 標題與工具列
c_title, c_refresh = st.columns([5, 1], vertical_alignment="center")
c_title.subheader("📚 媒體庫 (Library)")
if c_refresh.button("🔄", help="重新整理列表", use_container_width=True):
    st.rerun()

# 篩選器
col_filter, col_search = st.columns([1.5, 4])
with col_filter:
    filter_type = st.selectbox("顯示類別", ["All", "Movie", "TV"], label_visibility="collapsed")
with col_search:
    search_query = st.text_input("搜尋媒體...", placeholder="輸入關鍵字...", label_visibility="collapsed")

# 獲取資料
rows = get_all_media(filter_type, search_query)

if not rows:
    st.info("👋 資料庫目前是空的，請在左側點擊 **「🚀 開始全域掃描」**。")
else:
    st.caption(f"共 {len(rows)} 個項目")
    
    # --- 列表渲染 ---
    for row in rows:
        with st.container(border=True):
            # 欄位比例調整
            c1, c2, c3, c4, c5 = st.columns([0.8, 3.5, 0.8, 0.8, 0.8], vertical_alignment="center")
            
            # 1. 類型標籤 (使用 HTML CSS 渲染)
            if row['type'] == 'movie':
                c1.markdown('<div class="type-badge tb-movie">MOVIE</div>', unsafe_allow_html=True)
            else:
                c1.markdown('<div class="type-badge tb-tv">TV SHOW</div>', unsafe_allow_html=True)
            
            # 2. 名稱
            c2.markdown(f"**{row['name']}**")
            
            # 3. 來源硬碟
            c3.caption(f"Drive {row['drive_id']}")
            
            # 4. 更新按鈕
            if c4.button("更新", key=f"upd_{row['id']}", use_container_width=True):
                st.toast(f"正在更新: {row['name']}...", icon="🔄")
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            # 5. 詳細按鈕 (Primary Color)
            if c5.button("詳細", key=f"det_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])
