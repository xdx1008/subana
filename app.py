import streamlit as st
import json
import os
import posixpath
import threading
import time
import pandas as pd
from database import get_all_media, get_subtitles, clear_db, get_media_by_id
from logic import (
    run_library_scan, run_single_refresh, get_media_folders, list_folder_files, 
    execute_folder_rename, execute_folder_upload, execute_file_deletion, 
    execute_directory_purge, AlistClient, import_subs_to_target
)

# 設定路徑
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

st.set_page_config(page_title="Subana", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")

# --- CSS 極致優化 ---
st.markdown("""
<style>
    /* 1. 全局縮減 */
    .block-container { padding: 1rem 2rem 0rem 2rem !important; }
    .stApp { font-family: "Segoe UI", "Source Sans Pro", sans-serif; }
    
    /* 2. 隱藏原生 Header */
    header[data-testid="stHeader"] { display: none; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stSidebarCollapsedControl"] { display: none; }

    /* 3. Selected Header */
    .selected-header {
        background-color: #1e1e1e;
        border-left: 4px solid #ff4b4b;
        padding: 5px 15px;
        border-radius: 4px;
        margin-bottom: 5px;
        display: flex; align-items: center; justify-content: space-between; height: 40px;
        position: relative; z-index: 5;
        user-select: text !important; -webkit-user-select: text !important; cursor: text !important; pointer-events: auto !important;
    }
    .selected-header * { user-select: text !important; pointer-events: auto !important; }
    .selected-header-title { font-size: 1rem; font-weight: 700; color: #fff; }
    .selected-header-info { color: #888; font-size: 0.8rem; font-family: monospace; }

    /* 4. Log Box */
    .log-container { margin-top: 5px; border-top: 1px solid #333; padding-top: 5px; }
    .log-box { 
        font-family: 'Consolas', monospace; font-size: 11px; line-height: 1.3; color: #ccc;
        background-color: #0a0a0a; padding: 8px; border-radius: 4px; height: 120px;
        overflow-y: auto; display: flex; flex-direction: column-reverse; border: 1px solid #333;
    }
    .log-line { padding: 1px 0; border-bottom: 1px solid #222; }

    /* 5. Mini Log (Dialog) */
    .mini-log-box {
        font-family: 'Consolas', monospace; font-size: 10px; line-height: 1.2; color: #aaa;
        background-color: #000; padding: 5px; border-radius: 4px; height: 100px;
        overflow-y: auto; display: flex; flex-direction: column-reverse; border: 1px solid #444; 
        margin-top: 10px;
    }

    /* 6. Buttons */
    .stButton button { 
        border-radius: 4px; font-weight: 600; font-size: 0.85rem; padding: 0.2rem 0.5rem;
        height: 38px; width: 100%;
        border: 1px solid rgba(255,255,255,0.15);
    }
    div[role="dialog"] button { justify-content: flex-start !important; padding-left: 10px !important; }
    
    /* 7. File Uploader 按鈕化 */
    [data-testid="stFileUploader"] { padding-top: 0px; margin-top: 0px; display: block; }
    [data-testid="stFileUploader"] section { padding: 0px; min-height: 0px; background-color: transparent; border: none; }
    [data-testid="stFileUploader"] .st-emotion-cache-1fttcpj, [data-testid="stFileUploader"] small { display: none; }
    [data-testid="stFileUploader"] button {
        width: 100%; height: 38px; border-radius: 4px;
        background-color: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15);
        color: transparent !important; position: relative;
        display: flex; justify-content: center; align-items: center;
    }
    [data-testid="stFileUploader"] button:hover { border-color: #ff4b4b; background-color: rgba(255,255,255,0.1); }
    [data-testid="stFileUploader"] button::after {
        content: "💻 本機上傳"; color: #e4e4e7; font-size: 0.85rem; font-weight: 600;
        position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        pointer-events: none; white-space: nowrap; visibility: visible !important;
    }
    [data-testid="stFileUploader"] ul { display: none; }

    .tight-hr { margin: 8px 0 8px 0 !important; border: 0; border-top: 1px solid rgba(255,255,255,0.1); }
    footer {display: none;}
    .ep-row { padding: 2px 0; border-bottom: 1px solid #333; font-size: 0.9em; }
    h3 { margin-bottom: 5px !important; }
</style>
""", unsafe_allow_html=True)

# --- State ---
if 'active_dialog' not in st.session_state: st.session_state.active_dialog = None
if 'target_media_id' not in st.session_state: st.session_state.target_media_id = None
if 'target_media_name' not in st.session_state: st.session_state.target_media_name = ""
if 'selected_files' not in st.session_state: st.session_state.selected_files = set()
if 'last_selected_id' not in st.session_state: st.session_state.last_selected_id = None
if 'alist_browse_path' not in st.session_state: st.session_state.alist_browse_path = "/"
if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0
if 'confirm_purge' not in st.session_state: st.session_state.confirm_purge = False

# --- Helpers ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try: return json.load(open(CONFIG_FILE, 'r'))
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def manage_log_file(read_lines=15):
    if not os.path.exists(LOG_FILE): return '<div class="log-line" style="color:#666;">Waiting for logs...</div>'
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f: lines = f.readlines()
        if len(lines) > 500: lines = lines[-500:]
        try: 
            with open(LOG_FILE, "w", encoding='utf-8') as f: f.writelines(lines)
        except: pass
        display_lines = lines[-read_lines:]
        display_lines.reverse()
        return "".join([f'<div class="log-line">{l.strip()}</div>' for l in display_lines])
    except: return "Log Read Error"

def render_mini_log(lines=10):
    content = manage_log_file(lines)
    return f'<div class="mini-log-box">{content}</div>'

# --- 🔥 CALLBACKS ---

def reset_interaction_state():
    st.session_state.active_dialog = None
    st.session_state.selected_files = set()
    st.session_state.confirm_purge = False
    if 'mgr_logs' in st.session_state: del st.session_state.mgr_logs

def close_dialog():
    st.session_state.active_dialog = None
    st.session_state.selected_files = set()
    st.session_state.confirm_purge = False
    st.rerun()

def reset_purge_state():
    """切換目錄時重置刪除確認狀態"""
    st.session_state.confirm_purge = False

# [Top Nav Callbacks]
def open_settings_callback():
    st.session_state.active_dialog = 'settings'
    st.session_state.selected_files = set()

def start_scan_callback():
    st.session_state.active_dialog = None
    config = load_config()
    open(LOG_FILE, 'w').close()
    threading.Thread(target=run_library_scan, args=(config['url'], config['token'], config['path'])).start()

def clear_db_callback():
    st.session_state.active_dialog = None
    clear_db()

# [Action Callbacks]
def open_manager_callback(mid):
    st.session_state.target_media_id = mid
    st.session_state.active_dialog = 'manager'

def open_import_callback(mid):
    st.session_state.target_media_id = mid
    st.session_state.active_dialog = 'import'

def open_details_callback(mid):
    st.session_state.target_media_id = mid
    st.session_state.active_dialog = 'details'

def refresh_media_callback(mid, name):
    st.session_state.active_dialog = None 
    config = load_config()
    st.toast(f"掃描中: {name}", icon="⏳")
    threading.Thread(target=run_single_refresh, args=(config['url'], config['token'], mid)).start()

# --- Dialogs ---

@st.dialog("系統設定", width="medium")
def settings_dialog():
    config = load_config()
    with st.form("conf_form"):
        new_url = st.text_input("Alist URL", config.get("url", ""))
        new_token = st.text_input("Token", config.get("token", ""), type="password")
        new_path = st.text_input("根目錄 (Scan Root)", config.get("path", "/Cloud"))
        
        if st.form_submit_button("💾 儲存設定", type="primary", use_container_width=True):
            config.update({"url": new_url.rstrip('/'), "token": new_token, "path": new_path})
            save_config(config)
            st.toast("設定已儲存", icon="✅")
            time.sleep(0.5)
            close_dialog()

@st.dialog("檔案管理", width="large")
def file_manager_dialog():
    try: media_id = int(st.session_state.target_media_id)
    except: close_dialog(); return

    media_row = get_media_by_id(media_id)
    if not media_row: close_dialog(); return

    config = load_config()
    folders = get_media_folders(config['url'], config['token'], media_id)
    if not folders: st.error("目錄讀取失敗"); return

    folder_names = list(folders.keys())
    
    # 建立佈局容器
    top_area = st.container()
    st.markdown('<hr class="tight-hr">', unsafe_allow_html=True)
    list_area = st.container() 
    st.write("") 
    btn_area = st.container() 
    log_area = st.empty()     

    def run_task(ph, task_func, *args):
        t = threading.Thread(target=task_func, args=args)
        t.start()
        while t.is_alive():
            ph.markdown(render_mini_log(), unsafe_allow_html=True)
            time.sleep(0.5)
        t.join()
        ph.markdown(render_mini_log(), unsafe_allow_html=True)
        st.session_state.selected_files = set()
        st.session_state.confirm_purge = False
        
        if task_func == execute_directory_purge:
            st.session_state.active_dialog = None
            st.rerun()
        else:
            st.rerun()

    # 1. 頂部區域
    with top_area:
        c_title, c_sel, c_del = st.columns([5, 3, 2], vertical_alignment="bottom", gap="small")
        
        c_title.subheader(f"📂 {media_row['name']}")
        
        selected_folder_name = c_sel.selectbox(
            "切換目錄", folder_names, 
            label_visibility="collapsed", 
            key="target_selector_mgr",
            on_change=reset_purge_state # 切換時重置紅燈
        )
        target_path = folders[selected_folder_name]

        # 🔥 [NEW] 刪除目錄 (雙重確認)
        with c_del:
            if not st.session_state.confirm_purge:
                if st.button("🧨 刪除此目錄", type="primary", use_container_width=True, help="刪除整個資料夾，需二次確認"):
                    st.session_state.confirm_purge = True
                    st.rerun()
            else:
                c_sure, c_cancel = st.columns(2, gap="small")
                if c_sure.button("⚠️ 確定?", type="primary", use_container_width=True):
                    run_task(log_area, execute_directory_purge, config['url'], config['token'], target_path, media_id, selected_folder_name, config.get('path', '/Cloud'))
                # 🔥 這裡加上了 "取消" 文字
                if c_cancel.button("❌ 取消", use_container_width=True):
                    st.session_state.confirm_purge = False
                    st.rerun()

    # 2. 列表區
    with list_area:
        st.caption(f"📍 路徑: `{target_path}`")
        files = list_folder_files(config['url'], config['token'], target_path)
        
        if not files:
            st.info("目錄為空")
        else:
            df_files = pd.DataFrame(files) 
            df_files.insert(0, "選取", False)
            
            edited_df = st.data_editor(
                df_files,
                column_config={
                    "選取": st.column_config.CheckboxColumn(width="small"),
                    "name": st.column_config.TextColumn("檔名", width="large", disabled=True),
                    "type": st.column_config.TextColumn("類型", width="small", disabled=True)
                },
                hide_index=True,
                use_container_width=True,
                key=f"editor_mgr_{media_id}_{selected_folder_name}",
                height=300
            )
            if not edited_df.empty:
                st.session_state.selected_files = set(edited_df[edited_df["選取"]]["name"].tolist())

    # 3. 按鈕區 (3 欄: 刪選取 | 改名 | 上傳)
    with btn_area:
        c1, c2, c3 = st.columns(3, vertical_alignment="bottom", gap="small")
        
        with c1:
            if st.button("🗑️ 刪除選取", type="primary", disabled=not st.session_state.selected_files, use_container_width=True):
                files_to_del = list(st.session_state.selected_files)
                run_task(log_area, execute_file_deletion, config['url'], config['token'], target_path, files_to_del, config.get('path', '/Cloud'))
        
        with c2:
            if st.button("🛠️ 檔名對齊", use_container_width=True):
                run_task(log_area, execute_folder_rename, config['url'], config['token'], target_path)
                
        with c3:
            uploaded_files = st.file_uploader(
                "Upload", 
                accept_multiple_files=True, 
                label_visibility="collapsed",
                key=f"up_btn_{st.session_state.uploader_key}"
            )
            if uploaded_files:
                data = {f.name: f.getvalue() for f in uploaded_files}
                st.session_state.uploader_key += 1 
                run_task(log_area, execute_folder_upload, config['url'], config['token'], target_path, data)

    # 4. Log 區
    log_area.markdown(render_mini_log(), unsafe_allow_html=True)

@st.dialog("Alist 匯入工具", width="large")
def alist_import_dialog():
    try: media_id = int(st.session_state.target_media_id)
    except: close_dialog(); return

    media_row = get_media_by_id(media_id)
    if not media_row: close_dialog(); return

    config = load_config()
    client = AlistClient(config['url'], config['token'])
    folders = get_media_folders(config['url'], config['token'], media_id)
    if not folders: st.error("目錄讀取失敗"); return

    st.write("###### 🎯 匯入目標 (Destination)")
    folder_names = list(folders.keys())
    target_season = st.selectbox("目標目錄", folder_names, key="target_selector_imp", label_visibility="collapsed")
    target_path = folders[target_season]
    st.caption(f"路徑: `{target_path}`")
    
    st.markdown('<hr class="tight-hr">', unsafe_allow_html=True)

    st.write("###### ☁️ 來源瀏覽 (Source)")
    c_up, c_path = st.columns([1, 6])
    
    if c_up.button("⬆️ 上層", use_container_width=True):
        current = st.session_state.alist_browse_path.rstrip('/')
        if not current: current = '/'
        parent = posixpath.dirname(current) 
        if not parent or parent == '.': parent = '/'
        st.session_state.alist_browse_path = parent
        st.rerun()
    
    new_path = c_path.text_input("Path", value=st.session_state.alist_browse_path, label_visibility="collapsed")
    if new_path != st.session_state.alist_browse_path:
        st.session_state.alist_browse_path = new_path
        st.rerun()

    browse_items = client.list_files(st.session_state.alist_browse_path)
    with st.container(height=200, border=True):
        if browse_items:
            folders_only = [f for f in browse_items if f['is_dir']]
            folders_only.sort(key=lambda x: x['name'])
            
            if not folders_only:
                st.caption("此目錄無子資料夾，若包含字幕檔可直接匯入。")
            
            for f in folders_only:
                if st.button(f"📁 {f['name']}", key=f"nav_{f['name']}", use_container_width=True):
                    new_sub_path = posixpath.join(st.session_state.alist_browse_path, f['name'])
                    st.session_state.alist_browse_path = new_sub_path
                    st.rerun()
        else: st.caption("空目錄或無法讀取")

    st.markdown('<hr class="tight-hr">', unsafe_allow_html=True)
    
    mini_log_placeholder = st.empty()
    
    def run_task(ph, task_func, *args):
        t = threading.Thread(target=task_func, args=args)
        t.start()
        while t.is_alive():
            ph.markdown(render_mini_log(), unsafe_allow_html=True)
            time.sleep(0.5)
        t.join()
        ph.markdown(render_mini_log(), unsafe_allow_html=True)
        st.toast("匯入完成！", icon="✅")

    btn_label = f"📥 匯入字幕至 {target_season}"
    if st.button(btn_label, type="primary", use_container_width=True):
        run_task(mini_log_placeholder, import_subs_to_target, config['url'], config['token'], st.session_state.alist_browse_path, target_path)

    st.write("")
    mini_log_placeholder.markdown(render_mini_log(), unsafe_allow_html=True)

@st.dialog("媒體詳情", width="large")
def details_dialog():
    try: media_id = int(st.session_state.target_media_id)
    except: close_dialog(); return

    media_row = get_media_by_id(media_id)
    if not media_row: return

    st.subheader(f"ℹ️ {media_row['name']}")
    st.markdown("---")
    
    subs = get_subtitles(media_id)
    if not subs: st.warning("無資料"); return

    for s in subs:
        try:
            raw_json = s.get('subs') or s.get('subtitle_tracks')
            if not raw_json: continue
            episodes = json.loads(raw_json)
            
            if media_row['type'] == 'movie':
                for ep in episodes:
                    icon = "✅" if ep['status'] == 'ok' else "❌"
                    color = "#30d158" if ep['status'] == 'ok' else "#ff453a"
                    detail = ep['detail'].split("Stream #")[0] if "Stream #" in ep['detail'] else ep['detail']
                    st.markdown(f"<div class='ep-row'><div class='ep-icon'>{icon}</div><div style='flex-grow:1'><div style='font-weight:500;color:#e4e4e7'>{ep['name']}</div><div style='font-size:0.85em;color:{color};font-family:monospace'>{detail}</div></div></div>", unsafe_allow_html=True)
            else:
                total = len(episodes)
                ok_count = len([e for e in episodes if e['status'] == 'ok'])
                status_icon = "✅" if ok_count == total else "⚠️"
                if ok_count == 0: status_icon = "❌"
                with st.expander(f"📁 {s['season']} ｜ {status_icon} {ok_count}/{total} OK", expanded=False):
                    for ep in episodes:
                        icon = "✅" if ep['status'] == 'ok' else "❌"
                        color = "#30d158" if ep['status'] == 'ok' else "#ff453a"
                        detail = ep['detail'].split("Stream #")[0] if "Stream #" in ep['detail'] else ep['detail']
                        st.markdown(f"<div class='ep-row'><div class='ep-icon'>{icon}</div><div style='flex-grow:1'><div style='font-weight:500;color:#e4e4e7'>{ep['name']}</div><div style='font-size:0.85em;color:{color};font-family:monospace'>{detail}</div></div></div>", unsafe_allow_html=True)
        except: pass

# --- Main Layout ---
config = load_config()

col_title, col_btns = st.columns([1, 1], vertical_alignment="center")
with col_title:
    st.title("🎬 Subana")
with col_btns:
    c_set, c_scan, c_clean = st.columns(3)
    if c_set.button("⚙️ 設定", use_container_width=True, on_click=open_settings_callback): pass
    if c_scan.button("🚀 全域掃描", use_container_width=True, on_click=start_scan_callback): pass
    if c_clean.button("🗑️ 清空資料庫", use_container_width=True, on_click=clear_db_callback): pass

header_placeholder = st.empty()

rows = get_all_media("All", "")
if not rows:
    st.info("資料庫為空，請執行全域掃描。")
else:
    data = []
    for row in rows:
        is_ok = False
        if row['all_subs']:
            if "missing" not in row['all_subs']: is_ok = True
        data.append({
            "ID": row['id'], "Type": "Movie" if row['type'] == 'movie' else "TV", 
            "Status": "✅" if is_ok else "❌", "Drive": row['drive_id'], "Name": row['name']
        })
    df = pd.DataFrame(data)

    event = st.dataframe(
        df,
        column_config={
            "ID": None, 
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
            "Drive": st.column_config.TextColumn("Drive", width="small"),
            "Name": st.column_config.TextColumn("Name", width="large"),
        },
        use_container_width=True, hide_index=True, selection_mode="single-row",
        on_select=reset_interaction_state, height=350
    )

    if event.selection.rows:
        selected_idx = event.selection.rows[0]
        selected_row = df.iloc[selected_idx]
        current_id = int(selected_row["ID"])
        current_name = selected_row["Name"]
        
        header_placeholder.markdown(f"""
        <div class="selected-header">
            <div class="selected-header-title">{current_name}</div>
            <div class="selected-header-info">ID: {current_id}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state.last_selected_id != current_id:
            st.session_state.active_dialog = None
            st.session_state.last_selected_id = current_id
            st.rerun()
        
        c1, c2, c3, c4 = st.columns(4)
        if c1.button("📂 檔案管理", use_container_width=True):
            open_manager_callback(current_id)
            st.rerun()
        if c2.button("☁️ Alist 匯入", use_container_width=True):
            open_import_callback(current_id)
            st.rerun()
        if c3.button("🔄 手動刷新", use_container_width=True):
            refresh_media_callback(current_id, current_name)
        if c4.button("📄 詳細資料", use_container_width=True):
            open_details_callback(current_id)
            st.rerun()
    else:
        header_placeholder.markdown("<div style='height:40px;'></div>", unsafe_allow_html=True)

@st.fragment(run_every=1)
def footer_log():
    st.markdown('<div class="log-container">', unsafe_allow_html=True)
    st.caption("💻 System Log")
    st.markdown(f'<div class="log-box">{manage_log_file(10)}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

footer_log()

# --- Dialog Router ---
if st.session_state.active_dialog == 'settings':
    settings_dialog()
elif st.session_state.active_dialog == 'manager':
    file_manager_dialog()
elif st.session_state.active_dialog == 'import':
    alist_import_dialog()
elif st.session_state.active_dialog == 'details':
    details_dialog()
