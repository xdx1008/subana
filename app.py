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

    .log-terminal { font-family: 'SF Mono', 'Menlo', monospace; font-size: 11px; background-color: #0d1117; color: #c9d1d9; padding: 15px; border-radius: 8px; height: 200px; overflow-y: auto; border: 1px solid #30363d; display: flex; flex-direction: column; margin-top: 5px; }
    .log-line { padding: 4px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); word-wrap: break-word; white-space: pre-wrap; }
    [data-testid="stStatusWidget"] { visibility: hidden; }

    /* Episode Status Grid */
    .ep-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin-top: 10px; }
    .ep-card { background: rgba(0,0,0,0.3); padding: 8px; border-radius: 6px; font-size: 0.8rem; border: 1px solid #333; }
    .ep-ok { border-left: 3px solid #30d158; color: #ccc; }
    .ep-missing { border-left: 3px solid #ff453a; color: #ff453a; background: rgba(255, 69, 58, 0.05); }
</style>
""", unsafe_allow_html=True)

# --- Config & Log ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f: return json.load(f)
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def manage_log_file(max_lines=100):
    if not os.path.exists(LOG_FILE): return '<div class="log-line">No logs...</div>'
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
            with open(LOG_FILE, "w", encoding='utf-8') as f: f.writelines(lines)
        html = "".join([f'<div class="log-line">{l.strip()}</div>' for l in lines])
        return html if html else '<div class="log-line">Log Cleared</div>'
    except: return "Log Error"

# --- 核心邏輯：解析 JSON 判斷狀態 ---
def get_media_status(all_subs_str):
    """
    解析 DB 中的 all_subs 欄位 (現在是 JSON string 的串接)
    回傳: (is_complete, missing_count, total_count)
    """
    if not all_subs_str: return False, 0, 0
    
    try:
        # DB 中可能是多個 JSON string 串在一起 (因為 group_concat)，需要分割處理
        # 簡單做法：重新從 subtitles table 拉取正確的 JSON
        # 但這裡為了效能，我們假設 logic.py 存入的是完整的 JSON 陣列
        # 由於 database.py 的 group_concat 方式，這裡其實只適合做簡單判斷
        # 我們改為在 render 列表時不依賴 group_concat，而是依賴 has_missing flag (需修改 DB)
        # **權宜之計**：在列表頁只顯示「部分/全部」，詳情頁才解析 JSON
        pass 
    except: pass
    return False, 0, 0

# --- 詳細頁面：顯示集數矩陣 ---
@st.dialog("媒體詳情 (Episodes)")
def show_details(item_name, media_id):
    st.subheader(f"{item_name}")
    st.markdown("---")
    
    subs = get_subtitles(media_id) # 取得該媒體的所有季資料
    
    if not subs:
        st.warning("尚無分析資料")
        return

    for s in subs:
        season_name = s['season']
        json_data = s['subtitle_tracks']
        
        with st.expander(f"📁 {season_name}", expanded=True):
            try:
                episodes = json.loads(json_data) # 解析 JSON
                
                # 統計
                total = len(episodes)
                missing = len([e for e in episodes if e['status'] != 'ok'])
                
                if missing == 0:
                    st.success(f"✅ 完整 (Total: {total})")
                else:
                    st.error(f"❌ 缺少 {missing} 集 (Total: {total})")

                # 渲染集數卡片
                cols = st.columns(3) # 3欄佈局
                for i, ep in enumerate(episodes):
                    col = cols[i % 3]
                    status_class = "ep-ok" if ep['status'] == 'ok' else "ep-missing"
                    icon = "✅" if ep['status'] == 'ok' else "❌"
                    
                    with col:
                        st.markdown(f"""
                        <div class="ep-card {status_class}">
                            <div style="font-weight:bold;">{icon} {ep['name']}</div>
                            <div style="font-size:0.7em; opacity:0.8;">{ep['detail'][:30]}...</div>
                        </div>
                        """, unsafe_allow_html=True)
            except Exception as e:
                st.error(f"資料解析錯誤: {e}")
                st.text(json_data) # 顯示原始資料供除錯

# --- 主程式 ---
config = load_config()

with st.sidebar:
    st.title("🎬 Subana")
    st.markdown("---")
    # (Sidebar 代碼與 v7.12 相同，省略以節省篇幅)
    # ... 保留原有的 Sidebar 設定與按鈕 ...
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
    with st.expander("💻 系統終端機", expanded=False):
        st.markdown(f'<div class="log-terminal">{manage_log_file()}</div>', unsafe_allow_html=True)
log_section()

st.subheader("📚 媒體庫")

c1, c2 = st.columns([1.5, 5])
with c1:
    # 篩選器增加邏輯
    view_filter = st.selectbox("檢視模式", ["全部顯示", "只顯示缺字幕 (Missing Only)", "只顯示完整 (Complete Only)"], label_visibility="collapsed")
with c2:
    search_query = st.text_input("搜尋...", label_visibility="collapsed")

@st.fragment(run_every=3)
def render_list(v_filter, s_query):
    rows = get_all_media("All", s_query)
    if not rows: return

    final_rows = []
    
    # 這裡需要預處理資料來進行篩選
    for row in rows:
        # 我們需要「偷看」一下 subtitles table 來決定這個 row 是綠燈還是紅燈
        # 由於 get_all_media 使用 group_concat，字串中如果包含 "missing" 字眼，就代表有缺
        # logic.py 寫入時，如果缺字幕會寫 status: "missing" 到 JSON
        
        is_missing = "missing" in row['all_subs'] if row['all_subs'] else True
        is_complete = not is_missing

        if v_filter == "只顯示缺字幕 (Missing Only)" and is_complete: continue
        if v_filter == "只顯示完整 (Complete Only)" and is_missing: continue
        
        final_rows.append((row, is_complete))

    st.caption(f"共 {len(final_rows)} 個項目")

    for row, is_complete in final_rows:
        with st.container(border=True):
            c1, c2, c3, c4, c5, c6 = st.columns([1, 0.8, 3.5, 0.8, 0.8, 0.8], vertical_alignment="center")
            
            if row['type'] == 'movie': c1.markdown('<div class="type-badge tb-movie">MOVIE</div>', unsafe_allow_html=True)
            else: c1.markdown('<div class="type-badge tb-tv">TV</div>', unsafe_allow_html=True)
            
            # 🔥 智慧標籤
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
