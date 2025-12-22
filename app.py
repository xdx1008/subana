import streamlit as st
import json
import os
import threading
import time
from logic import run_analysis

CONFIG_FILE = 'config.json'
LOG_FILE = 'app.log'

st.set_page_config(page_title="Subana 設定", page_icon="🎬", layout="centered")

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
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            return "".join(f.readlines()[-lines:])
    return "尚無日誌..."

# --- 介面開始 ---
st.title("🎬 Subana 字幕分析器 (v4.0 GUI)")
st.markdown("---")

config = load_config()

with st.container():
    st.subheader("⚙️ 參數設定")
    col_url, col_token = st.columns([2, 1])
    new_url = col_url.text_input("Alist URL (不帶結尾斜線)", value=config.get("url", ""), placeholder="https://alist.example.com")
    new_token = col_token.text_input("Token", value=config.get("token", ""), type="password")
    new_path = st.text_input("掃描起始目錄 (Start Dir)", value=config.get("path", "/Cloud"))
    
    col1, col2 = st.columns(2)
    new_interval = col1.number_input("自動執行間隔 (秒)", value=config.get("interval", 3600), min_value=60, step=60)
    new_auto_run = col2.checkbox("啟用背景自動執行", value=config.get("auto_run", False), help="勾選後，後台將根據設定的間隔時間自動執行任務。")

    if st.button("💾 儲存設定"):
        new_config = {"url": new_url.rstrip('/'), "token": new_token, "path": new_path, "interval": new_interval, "auto_run": new_auto_run}
        save_config(new_config)
        st.success("設定已儲存！背景服務將自動讀取新設定。")

st.markdown("---")
st.subheader("🚀 操作區")

if st.button("▶️ 立即手動執行一次", type="primary"):
    if not new_url or not new_token:
        st.error("請先填寫完整的 URL 和 Token。")
    else:
        st.toast("任務已在背景啟動，請查看下方日誌...")
        # 使用 Thread 在背景執行，避免卡住介面
        t = threading.Thread(target=run_analysis, args=(new_url, new_token, new_path))
        t.start()

st.markdown("---")
st.subheader("📜 執行日誌 (最新 30 行)")

# 自動刷新日誌區塊
log_placeholder = st.empty()
if st.button("🔄 刷新日誌"):
    log_placeholder.code(tail_log(), language="text")
else:
    log_placeholder.code(tail_log(), language="text")

if st.button("🗑️ 清除所有日誌"):
    open(LOG_FILE, 'w').close()
    st.rerun()
