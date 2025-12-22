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

# --- CSS 優化 ---
st.markdown("""
<style>
    .block-container { padding-top: 4.5rem !important; padding-bottom: 5rem; }
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    section[data-testid="stSidebar"] { background-color: #1c1c1e; }
    
    .status-card { background-color: rgba(255,255,255,0.05); border-radius: 12px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); }
    .status-label { font-size: 0.75rem; color: #8e8e93; text-transform: uppercase; letter-spacing: 0.5px; }
    .status-value { font-size: 0.9rem; color: #ffffff; font-weight: 500; word-break: break-all; }
    .status-dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .dot-green { background-color: #30d158; box-shadow: 0 0 8px rgba(48, 209, 88, 0.4); }
    .dot-red { background-color: #ff453a; box-shadow: 0 0 8px rgba(255, 69, 58, 0.4); }

    .stButton button { border-radius: 8px !important; font-weight: 500; border: none; transition: transform 0.1s; }
    .stButton button:active { transform: scale(0.98); }

    div[data-testid="stContainer"] { background-color: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }

    /* 類型標籤 */
    .type-badge { padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 600; display: inline-block; min-width: 50px; width: auto; text-align: center; letter-spacing: 0.5px; white-space: nowrap; }
    .tb-movie { background-color: rgba(10, 132, 255, 0.15); color: #0a84ff; border: 1px solid rgba(10, 132, 255, 0.3); }
    .tb-tv { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }

    /* 中文字幕標籤 */
    .chi-badge { padding: 4px 8px; border-radius: 6px; font-size: 0.7rem; font-weight: bold; display: inline-block; min-width: 60px; text-align: center; }
    .chi-ok { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }
    .chi-no { background-color: rgba(255, 69, 58, 0.15); color: #ff453a; border: 1px solid rgba(255, 69, 58, 0.3); }

    .log-terminal { font-family: 'SF Mono', 'Menlo', monospace; font-size: 11px; line-height: 1.5; background-color: #0d1117; color: #c9d1d9; padding: 15px; border-radius: 8px; height: 200px; overflow-y: auto; border: 1px solid #30363d; display: flex; flex-direction: column; margin-top: 5px; }
    .log-line { padding: 4px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); word-wrap: break-word; white-space: pre-wrap; line-height: 1.4; }
    .log-line:last-child { border-bottom: none; }
    .log-line:nth-child(even) { background-color: rgba(255,255,255,0.02); }

    .detail-text { font-family: monospace; background: rgba(255,255,255,0.05); padding: 10px; border-radius: 8px; font-size: 0.85em; color: #eee; white-space: pre-wrap; line-height: 1.8; }
    [data-testid="stStatusWidget"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# --- 輔助函式 ---

# 🔥 修復點：正確的縮排語法
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def manage_log_file(max_lines=100):
    if not os.path.exists(LOG_FILE):
        return '<div class="log-line" style="color: #888;">系統待機中... (No logs)</div>'
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
            try:
                with open(LOG_FILE, "w", encoding='utf-8') as f: f.writelines(lines)
            except: pass
        formatted_html = []
        for line in lines:
            safe_line = line.strip().replace("<", "&lt;").replace(">", "&gt;")
            if safe_line: formatted_html.append(f'<div class="log-line">{safe_line}</div>')
        return "".join(formatted_html) if formatted_html else '<div class="log-line" style="color: #888;">Log 已清空</div>'
    except Exception as e: return f'<div class="log-line" style="color: red;">讀取日誌失敗: {str(e)}</div>'

def has_chinese_subs(sub_text):
    if not sub_text: return False
    text = sub_text.lower()
    keywords = ['chi', 'zho', 'chinese', 'cht', 'chs', '繁體', '简体', 'mandarin']
    return any(k in text for k in keywords)

@st.dialog("媒體詳情")
def show_details(item_name, media_id):
    st.subheader(f"{item_name}")
    st.markdown("---")
    subs = get_subtitles(media_id)
    if not subs: st.warning("⚠️ 此項目尚無內嵌字幕資料")
    else:
        for s in subs:
            with st.expander(f"📁 {s['season']}", expanded=True):
                st.markdown(f"<div class='detail-text'>{s['subtitle_tracks']}</div>", unsafe_allow_html=True)

# ==========================================
# 側邊欄
# ==========================================
config = load_config()

with st.sidebar:
    st.title("🎬 Subana")
    st.markdown("---")
    
    is_connected = bool(config.get('url') and config.get('token'))
    
    st.markdown(f"""
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
    """, unsafe_allow_html=True)

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
    st.markdown("**快速操作**")
    
    if st.button("🚀 開始全域掃描", use_container_width=True):
        if not is_connected: st.error("請先完成連線設定")
        else:
            st.toast("正在背景掃描...", icon="⏳")
            open(LOG_FILE, 'w').close()
            threading.Thread(target=run_library_scan, args=(config['url'], config['token'], config['path'])).start()
    
    if st.button("🗑️ 清空資料庫", use_container_width=True):
        clear_db()
        st.toast("資料庫已清空", icon="🗑️")
        time.sleep(1)
        st.rerun()

# ==========================================
# 主畫面
# ==========================================

@st.fragment(run_every=1)
def log_section():
    with st.expander("💻 系統終端機 (System Log)", expanded=False):
        log_html = manage_log_file(max_lines=100)
        st.markdown(f'<div class="log-terminal">{log_html}</div>', unsafe_allow_html=True)

log_section()

st.subheader("📚 媒體庫 (Library)")

# 篩選器
col_type, col_chi, col_search = st.columns([1.5, 1.5, 4])
with col_type:
    filter_type = st.selectbox("類型", ["All", "Movie", "TV"], label_visibility="collapsed")
with col_chi:
    filter_subs = st.selectbox("字幕狀態", ["全部顯示", "有中文字幕 (✅)", "無中文字幕 (❌)"], label_visibility="collapsed")
with col_search:
    search_query = st.text_input("搜尋媒體...", placeholder="輸入關鍵字並按 Enter 搜尋...", label_visibility="collapsed")

@st.fragment(run_every=3)
def render_library_list(f_type, s_query, f_subs):
    rows = get_all_media(f_type, s_query)

    if not rows:
        st.info("👋 資料庫目前是空的，請在左側點擊 **「🚀 開始全域掃描」**。")
        return

    # Python 端進行字幕篩選
    filtered_rows = []
    for row in rows:
        has_chi = has_chinese_subs(row['all_subs'])
        if f_subs == "有中文字幕 (✅)" and not has_chi: continue
        if f_subs == "無中文字幕 (❌)" and has_chi: continue
        filtered_rows.append(row)

    st.caption(f"共 {len(filtered_rows)} 個項目")
    
    for row in filtered_rows:
        has_chi = has_chinese_subs(row['all_subs'])
        
        with st.container(border=True):
            # 比例配置
            c1, c2, c3, c4, c5, c6 = st.columns([1, 0.8, 3.5, 0.8, 0.8, 0.8], vertical_alignment="center")
            
            # 1. 類型
            if row['type'] == 'movie':
                c1.markdown('<div class="type-badge tb-movie">MOVIE</div>', unsafe_allow_html=True)
            else:
                c1.markdown('<div class="type-badge tb-tv">TV</div>', unsafe_allow_html=True)
            
            # 2. 字幕標籤
            if has_chi:
                c2.markdown('<div class="chi-badge chi-ok">✓ CHI</div>', unsafe_allow_html=True)
            else:
                c2.markdown('<div class="chi-badge chi-no">✕ NONE</div>', unsafe_allow_html=True)
            
            # 3. 名稱
            c3.markdown(f"**{row['name']}**")
            
            # 4. 來源
            c4.caption(f"Drive {row['drive_id']}")
            
            # 5. 更新按鈕
            if c5.button("更新", key=f"upd_{row['id']}", use_container_width=True):
                st.toast(f"正在更新: {row['name']}...", icon="🔄")
                threading.Thread(target=run_single_refresh, 
                                 args=(config['url'], config['token'], row['id'])).start()
            
            # 6. 詳細按鈕
            if c6.button("詳細", key=f"det_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])

render_library_list(filter_type, search_query, filter_subs)
