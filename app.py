import streamlit as st
import json
import os
import threading
import time
from logic import run_analysis, run_renamer

DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

st.set_page_config(page_title="Subana 工具箱", page_icon="🧰", layout="centered")

def load_config():
    default_config = {
        "url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False,
        "rename_video_dir": "", "rename_sub_dir": ""
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                saved = json.load(f)
                default_config.update(saved) # 合併設定
                return default_config
        except: pass
    
    if not os.path.exists(CONFIG_FILE): save_config(default_config)
    return default_config

def save_config(config):
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=2)

def tail_log(lines=30):
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
                return "".join(f.readlines()[-lines:])
        except: return "讀取日誌失敗..."
    return "尚無日誌..."

# --- UI ---
st.title("🧰 Subana 全能工具箱")
st.caption("v5.0 Integrated | Analysis + Renamer")

config = load_config()

# 全域設定
with st.expander("🌍 全域連線設定 (Global Config)", expanded=True):
    col1, col2 = st.columns([2, 1])
    g_url = col1.text_input("Alist URL", value=config.get("url"), placeholder="https://alist.example.com")
    g_token = col2.text_input("Token", value=config.get("token"), type="password")

# 分頁功能
tab1, tab2, tab3 = st.tabs(["📊 媒體分析", "Rn 字幕對齊", "📜 系統日誌"])

# --- Tab 1: 分析器 ---
with tab1:
    st.subheader("內嵌字幕分析 & 報告")
    ana_path = st.text_input("分析起始目錄", value=config.get("path"))
    
    c1, c2 = st.columns(2)
    ana_interval = c1.number_input("自動循環 (秒)", value=config.get("interval"), min_value=60)
    ana_auto = c2.checkbox("啟用背景自動分析", value=config.get("auto_run"))

    if st.button("💾 儲存分析設定"):
        config.update({"url": g_url.rstrip('/'), "token": g_token, "path": ana_path, "interval": ana_interval, "auto_run": ana_auto})
        save_config(config)
        st.success("設定已儲存！")

    st.divider()
    if st.button("▶️ 立即執行分析"):
        if not g_url or not g_token: st.error("請填寫 URL 與 Token")
        else:
            st.toast("分析任務已啟動...")
            threading.Thread(target=run_analysis, args=(g_url, g_token, ana_path)).start()

# --- Tab 2: 對齊器 ---
with tab2:
    st.subheader("字幕檔名自動對齊")
    st.info("將字幕檔名修改為與影片一致 (基於 SxxExx 匹配)")
    
    r_vid_dir = st.text_input("影片資料夾", value=config.get("rename_video_dir", ""))
    r_sub_dir = st.text_input("字幕資料夾", value=config.get("rename_sub_dir", ""))
    
    # 同步按鈕
    if st.checkbox("字幕與影片在同一資料夾"):
        r_sub_dir = r_vid_dir
        st.caption(f"目前字幕路徑: {r_sub_dir}")

    col_btn1, col_btn2 = st.columns(2)
    
    # 預覽按鈕
    if col_btn1.button("🔍 掃描預覽 (Dry Run)"):
        if not g_url or not g_token: st.error("請填寫 URL 與 Token")
        else:
            # 暫存路徑設定
            config.update({"rename_video_dir": r_vid_dir, "rename_sub_dir": r_sub_dir})
            save_config(config)
            
            st.toast("預覽掃描中...")
            threading.Thread(target=run_renamer, args=(g_url, g_token, r_vid_dir, r_sub_dir, True)).start()

    # 執行按鈕
    if col_btn2.button("⚡ 確認並改名 (Execute)", type="primary"):
        if not g_url or not g_token: st.error("請填寫 URL 與 Token")
        else:
            st.toast("改名任務執行中...")
            threading.Thread(target=run_renamer, args=(g_url, g_token, r_vid_dir, r_sub_dir, False)).start()

# --- Tab 3: 日誌 ---
with tab3:
    c_l1, c_l2 = st.columns([3, 1])
    auto_scroll = c_l1.toggle("🔴 即時監控 Log", value=True)
    if c_l2.button("🗑️ 清空"): open(LOG_FILE, 'w').close(); st.rerun()

    log_box = st.empty()
    
    if auto_scroll:
        while True:
            log_box.code(tail_log(50), language="text")
            time.sleep(1)
    else:
        log_box.code(tail_log(50), language="text")
