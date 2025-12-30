from nicegui import ui, app, run
import os
import json
import threading
import time
import pandas as pd
from collections import deque
from datetime import datetime
import asyncio

# 引入後端邏輯 (直接沿用)
from database import get_all_media, get_subtitles, clear_db, get_media_by_id
from logic import (
    run_library_scan, run_single_refresh, get_media_folders, list_folder_files, 
    execute_folder_rename, execute_folder_upload, execute_file_deletion, 
    execute_directory_purge, AlistClient, import_subs_to_target,
    get_detailed_media_info
)

# --- 設定與路徑 ---
DATA_DIR = '/app/data'
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'app.log')

# --- 輔助函式 ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try: return json.load(open(CONFIG_FILE, 'r'))
        except: pass
    return {"url": "", "token": "", "path": "/Cloud", "interval": 3600, "auto_run": False, "rclone_conf": "/root/.config/rclone/rclone.conf"}

def save_config(new_conf):
    with open(CONFIG_FILE, 'w') as f: json.dump(new_conf, f, indent=2)

def read_logs():
    if not os.path.exists(LOG_FILE): return ["Waiting for logs..."]
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='ignore') as f:
            lines = list(deque(f, maxlen=50))
            return [l.strip() for l in reversed(lines)] # 反轉，最新的在上面
    except: return ["Log Read Error"]

# --- UI 建構 ---
@ui.page('/')
def main_page():
    # 全局樣式：暗色主題，無邊距
    ui.colors(primary='#ff4b4b', secondary='#262730', accent='#1e1e1e', dark='#0e1117')
    ui.query('body').classes('bg-[#0e1117] text-white p-0 m-0 overflow-hidden') # 禁止整個 body 捲動，改用區域捲動

    # =========================================================================
    # 1. 頂部導航列 (Header)
    # =========================================================================
    with ui.row().classes('w-full items-center justify-between p-4 bg-[#1e1e1e] border-l-4 border-[#ff4b4b] shadow-md h-16'):
        ui.label('🎬 Subana').classes('text-2xl font-bold tracking-wider')
        
        with ui.row().classes('gap-3'):
            ui.button('設定', icon='settings', on_click=lambda: settings_dialog.open()).props('flat color=white')
            
            async def run_scan():
                cfg = load_config()
                ui.notify('🚀 全域掃描已啟動')
                # 在背景執行，避免卡住 UI
                await run.io_bound(run_library_scan, cfg['url'], cfg['token'], cfg['path'])
                grid.update_rows() # 掃描完刷新表格
                ui.notify('🏁 掃描完成', type='positive')

            ui.button('掃描', icon='rocket_launch', on_click=run_scan).props('outline color=white')
            
            def run_clear():
                clear_db()
                grid.update_rows()
                ui.notify('資料庫已清空', type='warning')
            
            ui.button('清空', icon='delete', on_click=run_clear).props('outline color=red')

    # =========================================================================
    # 2. 主要內容區 (Grid)
    # =========================================================================
    # 取得資料函式
    def get_data():
        rows = get_all_media("All", "")
        return [
            {
                'id': r['id'], 
                'type': 'Movie' if r['type']=='movie' else 'TV', 
                'status': '✅' if r['all_subs'] and "missing" not in r['all_subs'] else '❌',
                'drive': r['drive_id'], 
                'name': r['name']
            } for r in rows
        ]

    # 定義操作區塊 (預設隱藏)
    action_panel = ui.row().classes('w-full bg-[#1c1c1c] p-2 items-center justify-between border-t border-gray-700 hidden')
    
    with action_panel:
        with ui.row().classes('items-center gap-4 pl-2'):
            selected_label = ui.label('').classes('text-lg font-bold text-white')
            selected_id_label = ui.label('').classes('text-sm text-gray-400 font-mono')
        
        with ui.row().classes('gap-2 pr-2'):
            btn_mgr = ui.button('管理', icon='folder').props('flat')
            btn_imp = ui.button('匯入', icon='cloud_upload').props('flat')
            btn_refresh = ui.button('刷新', icon='refresh').props('flat')
            btn_detail = ui.button('詳情', icon='description').props('unelevated color=primary')

    # 定義表格
    with ui.column().classes('w-full px-4 pt-4 flex-grow overflow-hidden'): # 讓表格佔滿剩餘空間
        grid = ui.aggrid({
            'columnDefs': [
                {'headerName': 'ID', 'field': 'id', 'width': 70, 'sortable': True},
                {'headerName': 'Type', 'field': 'type', 'width': 90, 'sortable': True},
                {'headerName': 'Status', 'field': 'status', 'width': 90, 'sortable': True},
                {'headerName': 'Name', 'field': 'name', 'flex': 1, 'filter': True, 'sortable': True},
            ],
            'rowData': get_data(),
            'rowSelection': 'single',
            'theme': 'balham-dark',
            'pagination': True,
            'paginationPageSize': 15,
        }).classes('w-full h-full')

    # 更新表格資料的方法
    grid.update_rows = lambda: grid.run_grid_method('setRowData', get_data())

    # 表格點擊事件
    async def on_row_click(e):
        rows = await grid.get_selected_rows()
        if rows:
            r = rows[0]
            action_panel.classes(remove='hidden')
            selected_label.text = r['name']
            selected_id_label.text = f"ID: {r['id']}"
            
            # 綁定按鈕動作 (使用 Closure 捕獲當前 ID)
            btn_mgr.on_click(lambda: open_file_manager(r['id'], r['name']))
            btn_imp.on_click(lambda: open_import_tool(r['id']))
            btn_detail.on_click(lambda: open_details(r['id'], r['name']))
            
            # 刷新邏輯
            async def do_refresh():
                ui.notify(f"正在刷新: {r['name']}...")
                cfg = load_config()
                await run.io_bound(run_single_refresh, cfg['url'], cfg['token'], r['id'])
                ui.notify('刷新完成', type='positive')
                # 這裡不一定需要刷新 grid，因為通常只變更了子內容，但為了保險可以刷一下
            
            # 移除舊的 event listener (避免重複綁定)
            btn_refresh.on_click(do_refresh, replace=True)

    grid.on('selectionChanged', on_row_click)

    # =========================================================================
    # 3. 底部日誌 (Log)
    # =========================================================================
    with ui.column().classes('w-full bg-black border-t border-gray-800 h-40 flex-none'):
        with ui.row().classes('w-full bg-[#1e1e1e] px-2 py-1 items-center gap-2 border-b border-gray-800'):
            ui.icon('terminal', size='xs', color='gray')
            ui.label('System Log').classes('text-xs text-gray-400')
        
        log_view = ui.column().classes('w-full h-full overflow-y-auto p-2 font-mono text-xs text-gray-400 gap-0')
        
        def update_log_view():
            log_view.clear()
            logs = read_logs()
            with log_view:
                for line in logs:
                    ui.label(line).classes('whitespace-pre-wrap')

        ui.timer(1.0, update_log_view)

    # =========================================================================
    # Dialog Components (功能視窗)
    # =========================================================================

    # --- A. 設定視窗 ---
    settings_dialog = ui.dialog()
    with settings_dialog, ui.card().classes('w-[500px] bg-[#262730] text-white p-6'):
        ui.label('⚙️ 系統設定').classes('text-xl font-bold mb-4')
        cfg = load_config()
        url = ui.input('Alist URL', value=cfg.get('url')).classes('w-full')
        token = ui.input('Token', value=cfg.get('token'), password=True).classes('w-full')
        path = ui.input('Root Path', value=cfg.get('path')).classes('w-full')
        rclone = ui.input('Rclone Config', value=cfg.get('rclone_conf')).classes('w-full')
        with ui.row().classes('w-full items-center mt-2'):
            auto_run = ui.switch('自動掃描', value=cfg.get('auto_run'))
            interval = ui.number('間隔(秒)', value=cfg.get('interval'), min=60).classes('w-24 ml-auto')
        
        with ui.row().classes('w-full justify-end mt-6 gap-2'):
            ui.button('取消', on_click=settings_dialog.close).props('flat color=grey')
            def save_s():
                cfg.update({'url':url.value.strip('/'), 'token':token.value, 'path':path.value, 'rclone_conf':rclone.value, 'auto_run':auto_run.value, 'interval':int(interval.value)})
                save_config(cfg)
                ui.notify('設定已儲存', type='positive')
                settings_dialog.close()
            ui.button('儲存', on_click=save_s).props('unelevated color=primary')

    # --- B. 檔案管理視窗 ---
    def open_file_manager(media_id, media_name):
        mgr_dialog = ui.dialog()
        # 讀取資料
        cfg = load_config()
        folders = get_media_folders(cfg['url'], cfg['token'], media_id)
        if not folders: ui.notify('無法讀取目錄', type='negative'); return

        folder_list = list(folders.keys())
        # 狀態
        current_folder = {'name': folder_list[0], 'path': folders[folder_list[0]]}
        selected_files = {'names': []} # 用 dict 包裝以在 callback 修改

        with mgr_dialog, ui.card().classes('w-[800px] h-[600px] bg-[#1e1e1e] text-white p-0 flex flex-col gap-0'):
            # Header
            with ui.row().classes('w-full bg-[#262730] p-3 items-center justify-between'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(f'📂 {media_name}').classes('text-lg font-bold')
                ui.button(icon='close', on_click=mgr_dialog.close).props('flat round dense color=white')
            
            # Toolbar
            with ui.row().classes('w-full p-3 gap-2 border-b border-gray-700 bg-[#262730]/50 items-center'):
                # 目錄選擇
                def on_folder_change(e):
                    current_folder['name'] = e.value
                    current_folder['path'] = folders[e.value]
                    refresh_file_list()
                
                ui.select(folder_list, value=folder_list[0], on_change=on_folder_change).classes('w-48').props('dense options-dense filled bg-color=grey-9')
                
                ui.space()
                
                # 功能按鈕
                async def delete_folder():
                    ui.notify('正在刪除目錄...', type='warning')
                    await run.io_bound(execute_directory_purge, cfg['url'], cfg['token'], current_folder['path'], media_id, current_folder['name'], cfg['path'])
                    ui.notify('目錄已刪除', type='positive')
                    mgr_dialog.close()
                ui.button('刪除目錄', on_click=delete_folder).props('outline color=red dense icon=delete_forever')

                async def align_names():
                    ui.notify('正在對齊檔名...')
                    await run.io_bound(execute_folder_rename, cfg['url'], cfg['token'], current_folder['path'])
                    refresh_file_list()
                    ui.notify('檔名對齊完成', type='positive')
                ui.button('檔名對齊', on_click=align_names).props('outline color=yellow dense icon=edit')

                async def delete_selected():
                    if not selected_files['names']: return
                    await run.io_bound(execute_file_deletion, cfg['url'], cfg['token'], current_folder['path'], selected_files['names'], cfg['path'])
                    refresh_file_list()
                    ui.notify('檔案已刪除', type='positive')
                del_btn = ui.button('刪除選取', on_click=delete_selected).props('unelevated color=red dense icon=delete').bind_visibility_from(selected_files, 'names', backward=lambda x: len(x)>0)

                # 上傳
                def handle_upload(e):
                    # e.content 是 file-like object
                    file_name = e.name
                    file_content = e.content.read()
                    execute_folder_upload(cfg['url'], cfg['token'], current_folder['path'], {file_name: file_content})
                    ui.notify(f'已上傳 {file_name}')
                    refresh_file_list()
                
                ui.upload(on_upload=handle_upload, auto_upload=True).props('dense flat color=white').classes('w-10 h-8') # 簡化上傳按鈕

            # File List (Table)
            table_container = ui.column().classes('w-full flex-grow p-0 overflow-hidden')
            
            def refresh_file_list():
                table_container.clear()
                files = list_folder_files(cfg['url'], cfg['token'], current_folder['path'])
                if not files: 
                    with table_container: ui.label('空目錄').classes('p-4 text-gray-500')
                    return
                
                # 轉換資料給 ui.table
                rows = [{'name': f['name'], 'type': f['type']} for f in files]
                
                with table_container:
                    file_table = ui.table({
                        'columnDefs': [
                            {'headerName': 'Name', 'field': 'name', 'checkboxSelection': True, 'headerCheckboxSelection': True, 'flex': 1},
                            {'headerName': 'Type', 'field': 'type', 'width': 100},
                        ],
                        'rowData': rows,
                        'rowSelection': 'multiple',
                        'suppressRowClickSelection': True, 
                        'theme': 'balham-dark'
                    }).classes('w-full h-full')
                    
                    # 監聽選擇事件
                    async def on_sel(e):
                        sel = await file_table.get_selected_rows()
                        selected_files['names'] = [r['name'] for r in sel]
                    file_table.on('selectionChanged', on_sel)

            refresh_file_list()
        
        mgr_dialog.open()

    # --- C. 匯入工具 ---
    def open_import_tool(media_id):
        imp_dialog = ui.dialog()
        cfg = load_config()
        folders = get_media_folders(cfg['url'], cfg['token'], media_id)
        if not folders: return
        
        folder_list = list(folders.keys())
        target_state = {'folder': folder_list[0]}
        
        # 瀏覽狀態
        browse_state = {'path': '/'} 

        with imp_dialog, ui.card().classes('w-[600px] h-[500px] bg-[#1e1e1e] text-white p-0 flex flex-col'):
            # Header
            with ui.row().classes('w-full bg-[#262730] p-3 items-center justify-between'):
                ui.label('☁️ Alist 匯入').classes('text-lg font-bold')
                ui.button(icon='close', on_click=imp_dialog.close).props('flat round dense color=white')

            # Body
            with ui.column().classes('p-4 w-full flex-grow gap-4'):
                # Target
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label('目標:').classes('font-bold w-12')
                    ui.select(folder_list, value=folder_list[0], on_change=lambda e: target_state.update({'folder': e.value})).classes('flex-grow').props('dense filled')

                ui.separator().classes('bg-gray-700')

                # Source Browser
                with ui.row().classes('w-full items-center gap-2'):
                    ui.button(icon='arrow_upward', on_click=lambda: nav_up()).props('flat dense')
                    path_input = ui.input(value='/').classes('flex-grow').props('dense filled')
                    ui.button(icon='arrow_forward', on_click=lambda: browse(path_input.value)).props('flat dense')
                
                # File List Container
                list_container = ui.column().classes('w-full h-48 overflow-y-auto bg-black/30 p-2 rounded border border-gray-700')
                client = AlistClient(cfg['url'], cfg['token'])

                def browse(path):
                    browse_state['path'] = path
                    path_input.value = path
                    list_container.clear()
                    items = client.list_files(path)
                    if items:
                        # 只顯示資料夾
                        dirs = [x for x in items if x['is_dir']]
                        dirs.sort(key=lambda x: x['name'])
                        with list_container:
                            if not dirs: ui.label('無子資料夾').classes('text-gray-500 text-sm')
                            for d in dirs:
                                ui.button(f"📁 {d['name']}", on_click=lambda n=d['name']: browse(posixpath.join(path, n))).props('flat dense align=left').classes('w-full text-left')
                    else:
                        with list_container: ui.label('讀取失敗或空目錄').classes('text-red-400')

                def nav_up():
                    parent = posixpath.dirname(browse_state['path'].rstrip('/')) or '/'
                    browse(parent)

                browse('/') # Init

            # Footer Action
            with ui.row().classes('w-full p-4 justify-end border-t border-gray-700'):
                async def do_import():
                    target_path = folders[target_state['folder']]
                    source_path = browse_state['path']
                    ui.notify(f'正在從 {source_path} 匯入...', type='info')
                    msg, _ = await run.io_bound(import_subs_to_target, cfg['url'], cfg['token'], source_path, target_path)
                    if msg == "完成": ui.notify('匯入成功', type='positive'); imp_dialog.close()
                    else: ui.notify(f'匯入失敗: {msg}', type='negative')
                
                ui.button('開始匯入', icon='download', on_click=do_import).props('unelevated color=primary')

        imp_dialog.open()

    # --- D. 詳細資訊視窗 ---
    def open_details(media_id, media_name):
        det_dialog = ui.dialog()
        row = get_media_by_id(media_id)
        subs = get_subtitles(media_id)

        with det_dialog, ui.card().classes('w-[800px] max-h-[80vh] bg-[#0e1117] text-white p-0 flex flex-col gap-0 border border-gray-700'):
            # Header
            with ui.row().classes('w-full bg-[#1e1e1e] p-3 items-center justify-between border-b border-gray-800'):
                ui.label(f'ℹ️ {media_name}').classes('text-lg font-bold')
                ui.button(icon='close', on_click=det_dialog.close).props('flat round dense color=white')
            
            # Content
            with ui.column().classes('w-full p-4 gap-3 overflow-y-auto'):
                if not subs:
                    ui.label('無資料').classes('text-gray-500')
                else:
                    for s in subs:
                        try:
                            eps = json.loads(s['subs'])
                            if row['type'] != 'movie':
                                ok_count = len([e for e in eps if e.get('status') == 'ok'])
                                with ui.expansion(f"{s['season']} ({ok_count}/{len(eps)})", value=True).classes('w-full bg-[#262730] rounded'):
                                    _render_ep_cards(eps)
                            else:
                                _render_ep_cards(eps)
                        except: pass
        det_dialog.open()

    def _render_ep_cards(episodes):
        for ep in episodes:
            status = ep.get('status', 'error')
            info = ep.get('media_info', {})
            
            with ui.card().classes('w-full bg-[#1e1e1e]/50 border border-gray-700 p-3 mb-2 gap-1'):
                # Card Header
                with ui.row().classes('w-full justify-between items-center'):
                    ui.label(ep['name']).classes('font-bold text-sm')
                    if status == 'ok': ui.label('✅ OK').classes('text-green-400 text-xs bg-green-900/30 px-2 rounded')
                    else: ui.label('⚠️ Missing').classes('text-red-400 text-xs bg-red-900/30 px-2 rounded')
                
                if "error" in info:
                    ui.label(f"Analysis Error: {info['error']}").classes('text-red-400 text-xs font-mono')
                else:
                    # Badges
                    with ui.row().classes('gap-2 my-1'):
                        if info.get('Resolution'):
                            res = int(info['Resolution'].split('x')[0])
                            t, c = ('4K', 'text-yellow-500 border-yellow-500') if res >= 3800 else ('1080P', 'text-blue-400 border-blue-400')
                            ui.label(t).classes(f'border {c} px-1 rounded text-[10px]')
                        if info.get('Video Dynamic Range') == 'HDR':
                            ui.label('HDR').classes('border border-orange-500 text-orange-500 px-1 rounded text-[10px]')
                        ac = info.get('Audio Codec', '')
                        if 'Atmos' in ac or 'TrueHD' in ac:
                            ui.label('Atmos/TrueHD').classes('border border-cyan-500 text-cyan-500 px-1 rounded text-[10px]')
                    
                    # Grid
                    with ui.element('div').classes('grid grid-cols-3 gap-2 bg-black/20 p-2 rounded text-[11px]'):
                        _info('VIDEO', info.get('Video Codec', '-'))
                        _info('BITRATE', info.get('Video Bitrate', '-'))
                        _info('AUDIO', info.get('Audio Codec', '-'))
                        _info('TIME', info.get('Run Time', '-'))
                        _info('SUBS', info.get('Subtitle Stream Count', 0))
                        _info('RES', info.get('Resolution', '-'))
                
                ui.label(ep.get('detail', '')).classes('text-gray-500 text-[10px] font-mono mt-1')

    def _info(label, val):
        with ui.column().classes('gap-0'):
            ui.label(label).classes('text-gray-600 scale-90 origin-left')
            ui.label(str(val)).classes('text-gray-300 font-medium')

    # 背景排程
    def auto_scan_check():
        if not state['scan_running']:
            # 這裡可以實作簡單的時間檢查
            pass
    ui.timer(60, auto_scan_check)

# 啟動
ui.run(title="Subana", port=8080, dark=True, reload=True, show=False)
