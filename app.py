import streamlit as st
import json
import os
import threading
import time
import posixpath
from database import get_all_media, get_subtitles, clear_db
from logic import run_library_scan, run_single_refresh, run_auto_fix, import_subs_from_folder, AlistClient

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
    
    .status-card { background-color: rgba(255,255,255,0.05); border-radius: 12px; padding: 12px; margin-bottom: 15px; border: 1px solid rgba(255,255,255,0.1); }
    .status-label { font-size: 0.75rem; color: #8e8e93; text-transform: uppercase; letter-spacing: 0.5px; }
    .status-value { font-size: 0.9rem; color: #ffffff; font-weight: 500; word-break: break-all; }
    .status-dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .dot-green { background-color: #30d158; box-shadow: 0 0 8px rgba(48, 209, 88, 0.4); }
    .dot-red { background-color: #ff453a; box-shadow: 0 0 8px rgba(255, 69, 58, 0.4); }
    .stButton button { border-radius: 8px !important; font-weight: 500; border: none; transition: transform 0.1s; }
    div[data-testid="stContainer"] { background-color: rgba(255,255,255,0.03); border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); }

    .type-badge { padding: 4px 10px; border-radius: 6px; font-size: 0.7rem; font-weight: 600; display: inline-block; min-width: 50px; text-align: center; white-space: nowrap; }
    .tb-movie { background-color: rgba(10, 132, 255, 0.15); color: #0a84ff; border: 1px solid rgba(10, 132, 255, 0.3); }
    .tb-tv { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }
    .chi-badge { padding: 4px 8px; border-radius: 6px; font-size: 0.7rem; font-weight: bold; display: inline-block; min-width: 70px; text-align: center; }
    .chi-ok { background-color: rgba(48, 209, 88, 0.15); color: #30d158; border: 1px solid rgba(48, 209, 88, 0.3); }
    .chi-no { background-color: rgba(255, 69, 58, 0.15); color: #ff453a; border: 1px solid rgba(255, 69, 58, 0.3); }

    .log-terminal { font-family: 'SF Mono', 'Menlo', monospace; font-size: 11px; background-color: #0d1117; color: #c9d1d9; padding: 10px; border-radius: 8px; height: 200px; border: 1px solid #30363d; display: flex; flex-direction: column-reverse; overflow-y: auto; }
    .log-line { padding: 2px 5px; border-bottom: 1px solid rgba(255,255,255,0.03); word-wrap: break-word; white-space: pre-wrap; flex-shrink: 0; }

    .ep-list-row { display: flex; align-items: flex-start; background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.05); padding: 12px 12px; font-size: 0.9em; }
    .ep-list-row:last-child { border-bottom: none; }
    .ep-status-icon { margin-right: 15px; font-size: 1.2em; min-width: 25px; margin-top: 2px; }
    .ep-content { display: flex; flex-direction: column; flex-grow: 1; overflow: hidden; }
    .ep-name { font-weight: 600; color: #fff; margin-bottom: 6px; word-break: break-all; }
    .ep-detail { font-family: 'SF Mono', 'Consolas', monospace; color: #aaa; font-size: 0.85em; white-space: pre-wrap; line-height: 1.4; background: rgba(0,0,0,0.2); padding: 6px; border-radius: 4px; }
    .status-ok { color: #30d158; }
    .status-missing { color: #ff453a; }
    
    /* File Browser Styles */
    .fb-row { display: flex; align-items: center; padding: 8px; border-bottom: 1px solid #333; cursor: pointer; }
    .fb-row:hover { background: rgba(255,255,255,0.05); }
    .fb-icon { margin-right: 10px; width: 20px; text-align: center; }
    .fb-name { flex-grow: 1; }
    
    [data-testid="stStatusWidget"] { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# --- Config & Log ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def manage_log_file(read_lines=100):
    if not os.path.exists(LOG_FILE):
        return '<div class="log-line">No logs...</div>'
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        if len(lines) > 200:
            lines = lines[-200:]
            try:
                with open(LOG_FILE, "w", encoding='utf-8') as f:
                    f.writelines(lines)
            except:
                pass
        
        display_lines = lines[-read_lines:]
        display_lines.reverse()
        
        html = "".join([f'<div class="log-line">{l.strip()}</div>' for l in display_lines])
        return html if html else '<div class="log-line">Log Cleared</div>'
    except Exception as e:
        return f'<div class="log-line">Log Error: {e}</div>'

def check_complete_status(all_subs_row):
    if not all_subs_row: return False
    return "missing" not in all_subs_row

# --- 檔案瀏覽器 Dialog ---
@st.dialog("選擇字幕來源目錄", width="large")
def file_browser_dialog(media_id, media_name):
    st.subheader(f"匯入字幕至: {media_name}")
    
    config = load_config()
    if not config.get('url') or not config.get('token'):
        st.error("請先設定連線")
        return

    # 初始化路徑：如果 session 中沒有，給一個預設值，但實際上我們會從外部按鈕傳入
    if "fb_path" not in st.session_state:
        st.session_state.fb_path = "/Cloud"

    client = AlistClient(config['url'], config['token'])
    
    # 顯示目前路徑
    c_path, c_up = st.columns([5, 1])
    c_path.text_input("目前路徑", value=st.session_state.fb_path, disabled=True)
    
    # 判斷是否為根目錄，如果是則禁用上一層
    is_root = (st.session_state.fb_path == "/" or st.session_state.fb_path == "")
    
    if c_up.button("⬆️ 上一層", disabled=is_root):
        # 自由導航：不設限，直接取 dirname
        parent = posixpath.dirname(st.session_state.fb_path)
        # 修正：posixpath.dirname("/") 回傳 "/"，不會報錯
        st.session_state.fb_path = parent
        st.rerun()

    st.markdown("---")

    # 取得檔案列表
    items = client.list_files(st.session_state.fb_path)
    
    if not items:
        st.info("此目錄為空")
    else:
        # 排序：資料夾在前
        items.sort(key=lambda x: (not x['is_dir'], x['name']))
        
        # 顯示列表 (只顯示資料夾，方便導航)
        for item in items:
            col1, col2 = st.columns([0.1, 0.9])
            
            if item['is_dir']:
                col1.write("📁")
                if col2.button(item['name'], key=f"dir_{item['name']}"):
                    # 進入子目錄
                    # 注意：如果目前是 "/"，join 後會變成 "//name"，需要處理
                    if st.session_state.fb_path == "/":
                        new_path = "/" + item['name']
                    else:
                        new_path = posixpath.join(st.session_state.fb_path, item['name'])
                    
                    st.session_state.fb_path = new_path
                    st.rerun()
            else:
                pass 

    st.markdown("---")
    st.markdown(f"**將從 ` {st.session_state.fb_path} ` 匯入所有字幕檔**")
    
    if st.button("✅ 確認匯入此目錄字幕", type="primary", use_container_width=True):
        st.toast("正在匯入並修復...", icon="⏳")
        # 執行匯入邏輯
        msg = import_subs_from_folder(config['url'], config['token'], media_id, st.session_state.fb_path)
        st.success(msg)
        time.sleep(2)
        st.rerun()

# --- 詳細頁面 ---
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
        episodes = []
        total = 0
        missing = 0
        label = f"📁 {season_name}"

        try:
            episodes = json.loads(json_data)
            total = len(episodes)
            missing = len([e for e in episodes if e['status'] != 'ok'])
            if missing == 0:
                label = f"📁 {season_name} | ✅ 完整 ({total} 集)"
            else:
                label = f"📁 {season_name} | ❌ 缺 {missing} 集 (共 {total} 集)"
        except:
            label = f"📁 {season_name} (Error)"

        with st.expander(label, expanded=(missing > 0)):
            try:
                st.markdown('<div style="border: 1px solid #333; border-radius: 8px; overflow: hidden;">', unsafe_allow_html=True)
                for ep in episodes:
                    is_ok = ep['status'] == 'ok'
                    icon = "✅" if is_ok else "❌"
                    status_class = "status-ok" if is_ok else "status-missing"
                    detail = ep['detail']
                    if "Stream #" in detail:
                        detail = "內嵌: " + detail.split("Stream #")[0] + "..."
                    
                    st.markdown(f"""
                    <div class="ep-list-row">
                        <div class="ep-status-icon {status_class}">{icon}</div>
                        <div class="ep-content">
                            <div class="ep-name">{ep['name']}</div>
                            <div class="ep-detail">{detail}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            except:
                pass

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

@st.fragment(run_every=1)
def log_section():
    with st.expander("💻 系統終端機", expanded=True):
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
            c1, c2, c3, c4, c5, c6, c7 = st.columns([0.8, 0.8, 3, 0.8, 0.8, 0.8, 0.8], vertical_alignment="center")
            
            if row['type'] == 'movie': c1.markdown('<div class="type-badge tb-movie">MOVIE</div>', unsafe_allow_html=True)
            else: c1.markdown('<div class="type-badge tb-tv">TV</div>', unsafe_allow_html=True)
            
            if is_complete: c2.markdown('<div class="chi-badge chi-ok">✓ ALL OK</div>', unsafe_allow_html=True)
            else: c2.markdown('<div class="chi-badge chi-no">✕ MISSING</div>', unsafe_allow_html=True)
            
            c3.markdown(f"**{row['name']}**")
            c4.caption(f"Drive {row['drive_id']}")
            
            # 🔥 修改點：點擊按鈕時，將當前媒體的 full_path 設為瀏覽器的初始路徑
            if c5.button("📂 匯入", key=f"imp_{row['id']}", help="從其他目錄匯入並修復字幕", use_container_width=True):
                st.session_state.fb_path = row['full_path']
                file_browser_dialog(row['id'], row['name'])
            
            if c6.button("更新", key=f"u_{row['id']}", use_container_width=True):
                st.toast(f"Updating {row['name']}...")
                threading.Thread(target=run_single_refresh, args=(config['url'], config['token'], row['id'])).start()
            
            if c7.button("詳細", key=f"d_{row['id']}", type="primary", use_container_width=True):
                show_details(row['name'], row['id'])

render_list(view_filter, search_query)
