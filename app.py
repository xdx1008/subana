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

st.set_page_config(page_title="Subana", page_icon="🎬", layout="wide")

# --- CSS 優化 ---
st.markdown("""
<style>
    .block-container { padding-top: 4.5rem !important; padding-bottom: 5rem; }
    .stApp { font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    section[data-testid="stSidebar"] { background-color: #1c1c1e; }
    
    /* 狀態卡片 & 按鈕 (保持 v8.0 樣式) */
    .status-card { background-color: rgba(255,255,255,0.05); border-radius: 12px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); }
    .status-label { font-size: 0.75rem; color: #8e8e93; text-transform: uppercase; letter-spacing: 0.5px; }
    .status-value { font-size: 0.9rem; color: #ffffff; font-weight: 500; word-break: break-all; }
    .status-dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .dot-green { background-color: #30d158; box-shadow: 0 0 8px rgba(48, 209, 88, 0.4); }
    .dot-red { background-color: #ff453a; box-shadow: 0 0 8px rgba(255, 69, 58, 0.4); }
    .stButton button { border-radius: 8px !important; font-weight: 500; border: none; transition: transform 0.1s; }
    div[data-testid="stContainer"] { background-color: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }

    /* 標籤樣式 */
    .type-badge { padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 600; display: inline-block; min-width: 50px; text-align: center; white-space: nowrap; }
    .tb-movie { background-color: rgba(10, 132, 255, 0.15); color: #0a84ff; border: 1px solid rgba(10, 132, 255, 0.3); }
    .tb-tv { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }
    .chi-badge { padding: 4px 8px; border-radius: 6px; font-size: 0.7rem; font-weight: bold; display: inline-block; min-width: 70px; text-align: center; }
    .chi-ok { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }
    .chi-no { background-color: rgba(255, 69, 58, 0.15); color: #ff453a; border: 1px solid rgba(255, 69, 58, 0.3); }

    /* 🔥 Log 終端機 (Auto-Scroll 核心技術) */
    .log-terminal { 
        font-family: 'SF Mono', 'Menlo', monospace; 
        font-size: 11px; 
        background-color: #0d1117; 
        color: #c9d1d9; 
        padding: 10px; 
        border-radius: 8px; 
        height: 200px; 
        border: 1px solid #30363d; 
        
        /* 關鍵：使用 column-reverse 讓內容從底部開始堆疊 */
        display: flex; 
        flex-direction: column-reverse; 
        overflow-y: auto; 
    }
    .log-line { 
        padding: 2px 5px; 
        border-bottom: 1px solid rgba(255,255,255,0.03); 
        word-wrap: break-word; 
        white-space: pre-wrap; 
        flex-shrink: 0; /* 防止被壓縮 */
    }

    /* 🔥 集數列表 (List View) */
    .ep-list-row {
        display: flex;
        align-items: center;
        background: rgba(255,255,255,0.03);
        border-bottom: 1px solid rgba(255,255,255,0.05);
        padding: 8px 12px;
        font-size: 0.9em;
    }
    .ep-list-row:last-child { border-bottom: none; }
    .ep-status-icon { margin-right: 12px; font-size: 1.1em; }
    .ep-name { font-weight: 600; width: 150px; color: #fff; }
    .ep-detail { flex-grow: 1; font-family: monospace; color: #aaa; font-size: 0.85em; white-space: pre-wrap; }
    
    .status-ok { color: #30d158; }
    .status-missing { color: #ff453a; }

    [data-testid="stStatusWidget"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# --- Config & Log ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try: return json.load(open(CONFIG_FILE, 'r'))
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def manage_log_file(read_lines=100):
    """
    讀取 Log：讀取最後 N 行，但輸出時反轉順序。
    配合 CSS column-reverse，達成「永遠顯示最新在最下面」的效果。
    """
    if not os.path.exists(LOG_FILE): return '<div class="log-line">No logs...</div>'
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
        
        # 截斷舊資料 (自動清理)
        if len(lines) > 200:
            lines = lines[-200:]
            try:
                with open(LOG_FILE, "w", encoding='utf-8') as f: f.writelines(lines)
            except: pass
            
        # 取最後 N 行顯示
        display_lines = lines[-read_lines:]
        
        # 🔥 關鍵：Python端反轉 List，讓最新的排在 List[0]
        # CSS column-reverse 會把 List[0] 放在容器的最底部
        display_lines.reverse()
        
        html = "".join([f'<div class="log-line">{l.strip()}</div>' for l in display_lines])
        return html if html else '<div class="log-line">Log Cleared</div>'
    except: return "Log Error"

# --- 核心邏輯：解析 JSON 判斷狀態 ---
def check_complete_status(all_subs_row):
    # 簡單判斷：如果資料庫裡存的 JSON string 含有 "missing"，代表有缺集數
    # 這是最快的方法，不用每次 render 都 load json
    if not all_subs_row: return False
    return "missing" not in all_subs_row

# --- 詳細頁面：集數列表 ---
@st.dialog("媒體詳情 (Episodes)", width="large")
def show_details(item_name, media_id):
    st.subheader(f"{item_name}")
    st.markdown("---")
    
    subs = get_subtitles(media_id)
    
    if not subs:
        st.warning("尚無分析資料")
        return

    for s in subs:
        season_name = s['season']
        json_data = s['subtitle_tracks']
        
        with st.expander(f"📁 {season_name}", expanded=True):
            try:
                episodes = json.loads(json_data)
                
                # 統計
                total = len(episodes)
                missing = len([e for e in episodes if e['status'] != 'ok'])
                
                if missing == 0:
                    st.success(f"✅ 全季完整 (共 {total} 集)")
                else:
                    st.error(f"❌ 缺少 {missing} 集 (共 {total} 集)")

                # 🔥 渲染列表 (List View)
                st.markdown('<div style="border: 1px solid #333; border-radius: 8px; overflow: hidden;">', unsafe_allow_html=True)
                
                for ep in episodes:
                    is_ok = ep['status'] == 'ok'
                    icon = "✅" if is_ok else "❌"
                    status_class = "status-ok" if is_ok else "status-missing"
                    # 清理詳細資訊，避免顯示過多 ffprobe 垃圾訊息
                    detail_text = ep['detail']
                    if "Stream #" in detail_text: # 簡化 ffprobe 輸出
                        detail_text = "內嵌: " + detail_text.split("Stream #")[0] + "..."
                    
                    st.markdown(f"""
                    <div class="ep-list-row">
                        <div class="ep-status-icon {status_class}">{icon}</div>
                        <div class="ep-name">{ep['name']}</div>
                        <div class="ep-detail">{detail_text}</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown('</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"資料解析錯誤: {e}")

# --- 主程式 ---
config = load_config()

with st.sidebar:
    st.title("🎬 Subana")
    st.markdown("---")
    
    with st.expander("⚙️ 連線設定"):
        with st.form("sidebar_config"):
            new_url = st.text_input("Alist URL", value=config.get("url", ""))
            new_token = st.text_input("Token", value=config.get("token", ""), type="password")
            new_path = st.text_input("根目錄", value=config.get("path", "/Cloud"))
            if st.form_submit_button("💾 儲存"):
                config.update({"url": new_url.rstrip('/'), "token": new_token, "path": new_path})
                save_config(config)
                st.rerun()
    
    st.markdown("---")
    if st.button("🚀 開始全域掃描", use_container_width=True):
        open(LOG_FILE, 'w').close()
        threading.Thread(target=run_library_scan, args=(config['url'], config['token'], config['path'])).start()
    if st.button("🗑️ 清空資料庫", use_container_width=True):
        clear_db(); st.rerun()

# --- 主畫面 ---
@st.fragment(run_every=1)
def log_section():
    with st.expander("💻 系統終端機", expanded=True):
        # 讀取最後 100 行
        st.markdown(f'<div class="log-terminal">{manage_log_file(100)}</div>', unsafe_allow_html=True)
log_section()

st.subheader("📚 媒體庫")

c1, c2 = st.columns([1.5, 5])
with c1:
    view_filter = st.selectbox("檢視模式", ["全部顯示", "只顯示缺字幕 (Missing)", "只顯示完整 (Complete)"], label_visibility="collapsed")
with c2:
    search_query = st.text_input("搜尋...", label_visibility="collapsed")

@st.fragment(run_every=3)
def render_list(v_filter, s_query):
    rows = get_all_media("All", s_query)
    if not rows: return

    final_rows = []
    
    for row in rows:
        is_complete = check_complete_status(row['all_subs'])

        if v_filter == "只顯示缺字幕 (Missing)" and is_complete: continue
        if v_filter == "只顯示完整 (Complete)" and not is_complete: continue
        
        final_rows.append((row, is_complete))

    st.caption(f"共 {len(final_rows)} 個項目")

    for row, is_complete in final_rows:
        with st.container(border=True):
            c1, c2, c3, c4, c5, c6 = st.columns([1, 0.8, 3.5, 0.8, 0.8, 0.8], vertical_alignment="center")
            
            if row['type'] == 'movie': c1.markdown('<div class="type-badge tb-movie">MOVIE</div>', unsafe_allow_html=True)
            else: c1.markdown('<div class="type-badge tb-tv">TV</div>', unsafe_allow_html=True)
            
            if is_complete:
                c2.markdown('<div class="chi-badge chi-ok">✓ ALL OK</div>', unsafe_allow_html=True)
            else:
                c2.markdown('<div class="chi-badge chi-no">✕ MISSING</div>', unsafe_allow_html=True)
            
            c3.markdown(f"**{row['name']}**")
            c4.caption(f"Drive {row['drive_id']}")
            
            if c5.button("更新", key=f"u_{row['id']}", use_container_width=True):
                st.toast(f"Updating {row['name']}...")
                threading.Thread(target=run_single_refresh, args=(config['url'], config['token'], row['id'])).start()
            
            if c6.button("詳細", key=f"d_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])

render_list(view_filter, search_query)
