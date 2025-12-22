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

# 頁面設定
st.set_page_config(page_title="Subana", page_icon="🎬", layout="wide")

# --- CSS 優化 (修復 Log 顯示與遮擋) ---
st.markdown("""
<style>
    /* 全域字體 */
    .stApp {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 側邊欄背景 */
    section[data-testid="stSidebar"] {
        background-color: #1c1c1e;
    }
    
    /* 狀態卡片 */
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

    /* 按鈕樣式 */
    .stButton button {
        border-radius: 8px !important;
        font-weight: 500;
        border: none;
        transition: transform 0.1s;
    }
    .stButton button:active { transform: scale(0.98); }

    /* 列表卡片容器 */
    div[data-testid="stContainer"] {
        background-color: rgba(255,255,255,0.03);
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.05);
    }

    /* 標籤 (Badges) */
    .type-badge {
        padding: 4px 8px;
        border-radius: 6px;
        font-size: 0.7rem;
        font-weight: bold;
        display: inline-block;
        width: 60px;
        text-align: center;
        letter-spacing: 0.5px;
    }
    .tb-movie { background-color: rgba(10, 132, 255, 0.15); color: #0a84ff; border: 1px solid rgba(10, 132, 255, 0.3); }
    .tb-tv { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }

    /* === Log 樣式 (重點修復) === */
    .log-terminal {
        font-family: 'SF Mono', 'Menlo', monospace;
        font-size: 11px;
        background-color: #0d1117; /* GitHub Dark Dimmed */
        color: #c9d1d9;
        padding: 0; /* 內距由單行控制 */
        border-radius: 8px;
        height: 250px; /* 固定高度 */
        overflow-y: auto; /* 允許捲動 */
        border: 1px solid #30363d;
        display: flex;
        flex-direction: column-reverse; /* 讓最新的在最上面 (或保持正常流向，視需求) - 這裡保持正常，JS控制捲動 */
        flex-direction: column;
    }
    
    /* Log 單行樣式 */
    .log-line {
        padding: 4px 12px;
        border-bottom: 1px solid rgba(255,255,255,0.03);
        word-wrap: break-word;
        white-space: pre-wrap; /* 確保換行 */
        line-height: 1.4;
    }
    .log-line:last-child { border-bottom: none; }
    /* 偶數行稍微變色，增加閱讀性 */
    .log-line:nth-child(even) { background-color: rgba(255,255,255,0.02); }

    /* 移除頂部過多空白 */
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

def manage_log_file(max_lines=100):
    """
    讀取 Log 並執行自動清理：
    1. 讀取所有內容
    2. 如果超過 max_lines，則截斷檔案保留最後 max_lines
    3. 回傳 HTML 格式的 Log 字串
    """
    if not os.path.exists(LOG_FILE):
        return '<div class="log-line" style="color: #888;">系統待機中... (No logs)</div>'

    try:
        # 讀取檔案
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # 自動清理機制：如果超過 100 行，重寫檔案
        if len(lines) > max_lines:
            lines = lines[-max_lines:] # 只保留最後 N 行
            try:
                with open(LOG_FILE, "w", encoding='utf-8') as f:
                    f.writelines(lines)
            except: pass # 避免寫入衝突導致報錯，稍微略過沒關係

        # 格式化輸出 HTML
        formatted_html = []
        for line in lines:
            safe_line = line.strip().replace("<", "&lt;").replace(">", "&gt;")
            if safe_line:
                formatted_html.append(f'<div class="log-line">{safe_line}</div>')
        
        # 如果是空的
        if not formatted_html:
            return '<div class="log-line" style="color: #888;">Log 已清空</div>'

        # 反轉順序讓最新的在最上面 (可選，這裡保持時間順序)
        # return "".join(reversed(formatted_html)) 
        return "".join(formatted_html)

    except Exception as e:
        return f'<div class="log-line" style="color: red;">讀取日誌失敗: {str(e)}</div>'

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

    # 1. 狀態儀表板
    is_connected = bool(config.get('url') and config.get('token'))
    
    status_html = f"""
    <div class="status-card">
        <div style="margin-bottom: 8px;">
            <span class="status-dot {'dot-green' if is_connected else 'dot-red'}"></span>
            <span style="color: {'#30d158' if is_connected else '#ff453a'}; font-weight: bold;">
                {'Online' if is_connected else 'Offline'}
            </span>
        </div>
        <div class="status-label">TARGET URL</div>
        <div class="status-value">{config.get('url') or '-'}</div>
        <div class="status-label" style="margin-top: 8px;">SCAN ROOT</div>
        <div class="status-value">{config.get('path') or '-'}</div>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)

    # 2. 設定表單
    with st.expander("⚙️ 連線設定"):
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
            # 掃描前先清空 log 檔，讓使用者看到新的開始
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

# 🔥 Log 區塊 (置頂 + 自動清理)
# 使用 st.fragment 進行局部刷新，不會影響下方列表
@st.fragment(run_every=1)
def log_section():
    # 預設展開，方便監控
    with st.expander("💻 系統終端機 (System Log - Auto Cleaned)", expanded=True):
        # 呼叫管理函式：讀取 + 自動清理超過 100 行的舊資料
        log_html = manage_log_file(max_lines=100)
        
        # 注入 HTML 渲染
        st.markdown(f'<div class="log-terminal">{log_html}</div>', unsafe_allow_html=True)

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
            
            # 1. 類型標籤
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
                # 更新前清除 Log 讓使用者看到最新進度
                open(LOG_FILE, 'w').close() 
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            # 5. 詳細按鈕
            if c5.button("詳細", key=f"det_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])
