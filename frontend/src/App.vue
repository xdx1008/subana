<template>
  <v-app theme="dark">
    <v-navigation-drawer 
      v-model="drawer" 
      :rail="!mobile && rail" 
      :temporary="mobile"
      :permanent="!mobile"
      expand-on-hover 
      color="#1E1E1E" 
      :width="260" 
      class="border-r border-grey-darken-3 d-flex flex-column"
      @update:rail="val => rail = val"
    >
      <v-list-item class="px-2 py-4">
        <div v-if="!rail || mobile" class="text-center fade-transition d-flex flex-column align-center">
             <v-icon color="primary" size="x-large" class="mb-2">mdi-cloud-sync</v-icon>
             <div class="text-h6 font-weight-black text-grey-lighten-2 text-wrap" style="line-height: 1.2;">
                 SUBANA MGR
             </div>
        </div>
        <div v-else class="text-center">
            <v-icon color="primary" size="large">mdi-cloud-sync</v-icon>
        </div>
      </v-list-item>

      <v-divider class="mb-2"></v-divider>
      <v-list density="compact" nav class="flex-grow-1">
        <v-list-item prepend-icon="mdi-movie-open" title="Media Library" value="media" @click="changeView('media')" :active="currentView==='media'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-sync" title="Rclone Sync" value="sync" @click="changeView('sync')" :active="currentView==='sync'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-notebook-outline" title="System Logs" value="logs" @click="changeView('logs')" :active="currentView==='logs'" color="primary" rounded="lg"></v-list-item>
        <v-list-item prepend-icon="mdi-cog" title="Settings" value="settings" @click="changeView('settings')" :active="currentView==='settings'" color="primary" rounded="lg"></v-list-item>
      </v-list>
      <template v-slot:append>
        <div v-if="(!rail || mobile)" class="pa-4 bg-grey-darken-4 border-t border-grey-darken-3 fade-transition">
            <div class="mb-4">
                <div class="text-caption font-weight-bold text-grey mb-2 d-flex align-center">
                    <v-icon size="x-small" class="mr-1">mdi-robot</v-icon> AUTOMATION STATUS
                </div>
                
                <div class="mb-2">
                    <div class="d-flex align-center text-caption text-grey-darken-1 mb-1">
                        <v-icon size="x-small" class="mr-1">mdi-sync</v-icon> SYNC
                        <v-spacer></v-spacer>
                        <v-progress-circular v-if="status.sync.running" indeterminate size="10" width="1" color="primary"></v-progress-circular>
                    </div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Last:</span><span class="mono-font">{{ status.sync.last }}</span></div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Next:</span><span class="mono-font text-primary">{{ status.sync.next }}</span></div>
                </div>

                <v-divider class="my-2 border-grey-darken-2"></v-divider>

                <div>
                     <div class="d-flex align-center text-caption text-grey-darken-1 mb-1">
                        <v-icon size="x-small" class="mr-1">mdi-radar</v-icon> SCAN
                        <v-spacer></v-spacer>
                        <v-progress-circular v-if="status.scan.running" indeterminate size="10" width="1" color="primary"></v-progress-circular>
                    </div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Last:</span><span class="mono-font">{{ status.scan.last }}</span></div>
                    <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Next:</span><span class="mono-font text-primary">{{ status.scan.next }}</span></div>
                </div>
            </div>
            
            <v-divider class="mb-3"></v-divider>
            
            <div>
                <div class="d-flex justify-space-between align-center mb-2">
                     <div class="text-caption font-weight-bold text-grey d-flex align-center"><v-icon size="x-small" class="mr-1">mdi-cloud</v-icon> STORAGE</div>
                     <v-btn icon="mdi-refresh" size="x-small" variant="text" density="compact" @click="fetchStatus(true)" :loading="checkingSpace" color="grey" title="Refresh Space"></v-btn>
                </div>
                <div class="d-flex justify-space-between text-caption text-grey-lighten-1 mb-1"><span>Free:</span><span class="mono-font text-white font-weight-bold">{{ status.space.free }}</span></div>
                <div class="d-flex justify-space-between text-caption text-grey-lighten-1"><span>Total:</span><span class="mono-font">{{ status.space.total }}</span></div>
            </div>
        </div>
      </template>
    </v-navigation-drawer>

    <v-main class="fill-height overflow-hidden" id="main-content">
      <div v-if="currentView === 'media'" class="d-flex flex-column h-100 w-100 overflow-hidden">
        
        <div class="px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3 d-flex flex-column flex-sm-row align-start align-sm-center gap-2 flex-shrink-0">
             
             <div class="d-flex align-center w-100" :style="mobile ? '' : 'max-width: auto; flex: 1;'">
                 <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer"></v-app-bar-nav-icon>
                 
                 <v-text-field 
                    v-model="search" 
                    prepend-inner-icon="mdi-magnify" 
                    label="Search..." 
                    density="compact" 
                    variant="outlined" 
                    hide-details 
                    class="mono-font flex-grow-1" 
                    :style="mobile ? '' : 'max-width: 300px'"
                    bg-color="#121212"
                 ></v-text-field>

                 <v-select
                    v-model="scanTarget"
                    :items="scanOptions"
                    label="Scan Target"
                    density="compact"
                    variant="outlined"
                    hide-details
                    bg-color="#121212"
                    style="max-width: 150px;"
                    class="ml-2 hidden-xs"
                 ></v-select>

                 <v-spacer class="hidden-sm-and-down"></v-spacer>
             </div>

             <div class="d-flex flex-wrap align-center justify-end w-100 w-sm-auto mt-1 mt-sm-0" style="gap: 8px;">
                 <v-btn color="error" variant="text" size="small" @click="clearDB" style="min-width: 0; padding: 0 8px;">
                     <v-icon>mdi-delete-sweep</v-icon>
                     <span class="d-none d-sm-inline ml-1">Clear DB</span>
                 </v-btn>
                 
                 <v-divider vertical class="mx-1 d-none d-sm-block"></v-divider>
                 
                 <v-btn color="info" variant="text" size="small" @click="generateStrm" style="min-width: 0; padding: 0 8px;">
                     <v-icon>mdi-file-video</v-icon>
                     <span class="d-none d-sm-inline ml-1">Gen STRM</span>
                 </v-btn>

                 <v-divider vertical class="mx-1 d-none d-sm-block"></v-divider>

                 <v-btn color="primary" :loading="status.scan.running" @click="startScan" variant="tonal" size="small" style="min-width: 0; padding: 0 8px;">
                     <v-icon :start="!mobile">mdi-radar</v-icon>
                     <span class="d-none d-sm-inline ml-1">{{ status.scan.running ? 'Scanning...' : 'Scan' }}</span>
                 </v-btn>
             </div>
        </div>
        
        <div class="flex-grow-1 w-100 bg-[#121212] overflow-hidden" style="min-height: 0;">
            <v-data-table 
              :headers="mediaHeaders" :items="mediaList" :search="search" density="compact" 
              class="bg-transparent h-100 sticky-header-table" fixed-header height="100%" hover 
              :items-per-page="15" :items-per-page-options="[15, 25, 50, 100, { value: -1, title: 'All' }]"
            >
                <template #item.actions="{ item }">
                    <div class="d-flex justify-end gap-1">
                        <v-btn icon="mdi-refresh" size="x-small" variant="text" color="grey" @click="refreshItem(getRaw(item))" title="Refresh"></v-btn>
                        <v-btn icon="mdi-folder-open" size="x-small" variant="text" color="info" @click="openFileManager(getRaw(item))" title="Files"></v-btn>
                        <v-btn icon="mdi-file-document-outline" size="x-small" variant="text" color="warning" @click="openDetails(getRaw(item))" title="Details"></v-btn>
                    </div>
                </template>
                <template #item.status="{ item }">
                    <v-chip size="x-small" :color="getRaw(item).status === 'OK' ? 'green' : 'red'" label variant="flat" class="font-weight-bold">{{ getRaw(item).status }}</v-chip>
                </template>
                <template #item.is_multi="{ item }">
                    <v-chip v-if="getRaw(item).is_multi" size="x-small" color="orange" variant="outlined" class="px-1" style="height: 20px;">Multi</v-chip>
                    <span v-else class="text-caption text-grey-darken-2">Single</span>
                </template>
                <template #item.drive="{ item }"><span class="text-caption text-grey">{{ getRaw(item).drive }}</span></template>
                <template #item.name="{ item }"><span class="text-body-2 font-weight-medium text-grey-lighten-1">{{ getRaw(item).name }}</span></template>
                <template #no-data>
                    <div class="d-flex flex-column align-center justify-center pa-8 text-grey mt-10">
                        <v-icon size="64" class="mb-4" color="grey-darken-3">mdi-database-off</v-icon>
                        <div class="text-h6 mb-2">Library is Empty</div>
                        <v-btn color="primary" variant="tonal" @click="startScan">Start Scan</v-btn>
                    </div>
                </template>
            </v-data-table>
        </div>
      </div>

      <div v-if="currentView === 'sync'" class="d-flex flex-column h-100 w-100 overflow-hidden">
        <div class="px-4 py-3 bg-grey-darken-4 border-b border-grey-darken-3 d-flex flex-wrap align-center justify-space-between gap-3 flex-shrink-0">
           <div class="d-flex flex-wrap align-center gap-3 w-100">
               <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
               
               <div class="d-flex flex-wrap align-center gap-4 flex-grow-1">
                   <div class="d-flex align-center gap-2" title="Upload Speed">
                       <v-icon color="primary" size="small">mdi-upload-network</v-icon>
                       <span class="text-caption text-grey font-weight-bold hidden-xs">Speed:</span>
                       <span class="text-subtitle-2 mono-font font-weight-bold text-blue-lighten-1">{{ syncData.speed }}</span>
                   </div>
                   <div class="d-flex align-center gap-2" title="ETA">
                       <v-icon color="info" size="small">mdi-timer-sand</v-icon>
                       <span class="text-caption text-grey font-weight-bold hidden-xs">ETA:</span>
                       <span class="text-subtitle-2 mono-font text-grey-lighten-1">{{ syncData.eta }}</span>
                   </div>
               </div>
               
               <div class="d-flex gap-2">
                   <v-btn variant="flat" size="small" color="success" :disabled="syncRunning" @click="startSync" class="font-weight-bold" style="min-width: 0;">
                        <v-icon start>mdi-play</v-icon><span class="d-none d-sm-inline">Sync</span>
                   </v-btn>
                   <v-btn variant="tonal" size="small" color="error" :disabled="!syncRunning" @click="stopSync" style="min-width: 0;">
                        <v-icon start>mdi-stop</v-icon><span class="d-none d-sm-inline">Stop</span>
                   </v-btn>
               </div>
           </div>
        </div>
        <div class="flex-grow-1 w-100 bg-[#121212] d-flex flex-column overflow-hidden relative">
            <div class="d-flex px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3 text-caption text-uppercase font-weight-bold text-grey flex-shrink-0">
                <div class="flex-grow-1">File Name</div><div style="width: 200px;" class="d-none d-sm-block">Progress</div><div class="text-right" style="width: 120px;">Speed</div>
            </div>
            <div class="flex-grow-1 w-100 overflow-y-auto">
                 <div v-for="(info, fname) in syncData.files" :key="fname" class="d-flex align-center px-4 py-1 border-b border-grey-darken-3 hover:bg-white/5 transition-colors">
                     <div class="flex-grow-1 d-flex align-center gap-2 overflow-hidden mr-4"><v-icon size="small" color="grey">mdi-file-outline</v-icon><span class="text-caption text-grey-lighten-1 text-truncate" :title="fname">{{ fname }}</span></div>
                     <div style="width: 200px;" class="d-none d-sm-block"><v-progress-linear :model-value="info.pct" color="primary" height="4" rounded></v-progress-linear></div>
                     <div class="text-right mono-font text-caption text-blue-lighten-2 ml-4" style="width: 120px;">{{ info.speed }}</div>
                 </div>
                 <div v-if="!syncRunning && Object.keys(syncData.files).length === 0" class="d-flex flex-column align-center justify-center fill-height text-grey-darken-3 opacity-50"><v-icon size="80" class="mb-4">mdi-cloud-sync-outline</v-icon><div class="text-h5 font-weight-bold">IDLE</div></div>
            </div>
        </div>
      </div>

      <div v-if="currentView === 'logs'" class="d-flex flex-column h-100 w-100 overflow-hidden bg-black">
         <div class="d-flex align-center px-4 py-2 bg-[#1E1E1E] border-b border-grey-darken-3">
             <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
             <div class="text-subtitle-2 font-weight-bold text-grey-lighten-1">System Logs</div>
             <v-spacer></v-spacer>
             <div v-if="autoScrollPaused" class="text-caption text-warning d-flex align-center fade-transition">
                 <v-icon size="x-small" class="mr-1">mdi-pause-circle-outline</v-icon> Auto-scroll Paused
             </div>
         </div>
         
         <div 
            class="flex-grow-1 pa-4 overflow-y-auto" 
            ref="logBox"
            @wheel="handleLogUserInteraction"
            @touchmove="handleLogUserInteraction"
            @mousedown="handleLogUserInteraction"
            @keydown="handleLogUserInteraction"
         >
             <div v-if="!logContent" class="text-grey-darken-2 text-center mt-10">No logs available yet...</div>
             <div class="mono-font text-caption text-grey-lighten-1" style="white-space: pre-wrap; line-height: 1.5; font-family: 'Consolas', monospace;">{{ logContent }}</div>
         </div>
      </div>

      <v-container v-if="currentView === 'settings'" fluid class="pa-4 h-100 overflow-y-auto">
           <div class="d-flex align-center mb-4">
                <v-app-bar-nav-icon v-if="mobile" variant="text" @click.stop="drawer = !drawer" class="mr-2"></v-app-bar-nav-icon>
                <div class="text-h6">Settings</div>
           </div>
           
           <v-card color="#1E1E1E" title="System Logs" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.log_max_size" label="Max Log File Size (MB)" type="number" variant="outlined" density="compact" bg-color="#222" hint="Old logs will be overwritten when size limit is reached." persistent-hint></v-text-field>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Alist Connection" class="mb-4" border>
              <v-card-text>
                  <v-text-field v-model="config.url" label="Alist URL" variant="outlined" density="compact" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.token" label="Token" variant="outlined" density="compact" type="password" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.path" label="Cloud Root Path" variant="outlined" density="compact" class="mb-3" bg-color="#222"></v-text-field>
                  <v-text-field v-model="config.rclone_conf" label="Rclone Config Path" variant="outlined" density="compact" bg-color="#222" hint="Absolute path inside container" persistent-hint></v-text-field>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="STRM Configuration" class="mb-4" border>
              <v-card-text>
                  <v-text-field 
                      v-model="config.strm_path" 
                      label="STRM Output Path" 
                      variant="outlined" 
                      density="compact" 
                      bg-color="#222" 
                      hint="指定 Alist 上存放 strm 檔的目標目錄 (例如: /Cloud/strm)" 
                      persistent-hint 
                      prepend-inner-icon="mdi-folder-play"
                      hide-details="auto"
                  ></v-text-field>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Rclone Sync Configuration" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.local_path" label="Local Source Path" variant="outlined" density="compact" bg-color="#222" prepend-inner-icon="mdi-folder-home"></v-text-field>
                      </v-col>
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.remote_path" label="Remote Destination Path" variant="outlined" density="compact" bg-color="#222" prepend-inner-icon="mdi-cloud-upload"></v-text-field>
                      </v-col>
                  </v-row>
                  <v-row align="center">
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.transfers" label="Transfers (Threads)" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.bwlimit" label="Bandwidth Limit" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-text-field v-model="config.sync_interval" label="Interval (Minutes)" variant="outlined" density="compact" bg-color="#222"></v-text-field>
                      </v-col>
                      <v-col cols="6" md="3">
                          <v-switch v-model="config.auto_sync" label="Auto Sync (Timer)" color="success" hide-details inset></v-switch>
                          <div class="text-caption text-grey ml-2 mt-1">Runs every {{config.sync_interval}} mins</div>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <v-card color="#1E1E1E" title="Automation" class="mb-4" border>
              <v-card-text>
                  <v-row align="center">
                      <v-col cols="12" md="6">
                          <v-switch v-model="config.auto_run" label="Enable Auto Library Scan" color="primary" hide-details inset></v-switch>
                          <div class="text-caption text-grey ml-2 mt-1">Automatically checks for new files in cloud folders.</div>
                      </v-col>
                      <v-col cols="12" md="6">
                          <v-text-field v-model="config.interval" label="Scan Interval (Seconds)" type="number" variant="outlined" density="compact" bg-color="#222" hide-details></v-text-field>
                          <div class="text-caption text-grey mt-1">Frequency of library updates (default: 3600s).</div>
                      </v-col>
                  </v-row>
              </v-card-text>
           </v-card>

           <div class="d-flex justify-end pb-6">
               <v-btn color="primary" size="large" variant="flat" prepend-icon="mdi-content-save" @click="saveConfig">Save All Changes</v-btn>
           </div>
      </v-container>
      
      <v-dialog v-model="fmDialog" width="auto" max-width="95vw" scrollable>
        <v-card color="#1E1E1E">
            <v-card-title class="d-flex flex-wrap align-center text-subtitle-1 border-b border-grey-darken-3 bg-[#252525] py-2">
                <div class="d-flex align-center overflow-hidden mr-auto mb-2 mb-sm-0" style="min-width: 150px; max-width: 100%;">
                    <v-icon start color="primary">mdi-folder</v-icon> 
                    <span class="text-truncate">{{ selectedMedia?.name }}</span>
                    <v-chip size="x-small" class="ml-2 flex-shrink-0" color="grey-lighten-1" variant="flat">{{ fileList.length }} items</v-chip>
                </div>
                
                <div class="d-flex align-center gap-2 flex-grow-1 flex-sm-grow-0 justify-end" style="width: 100%; sm:width: auto;">
                    <v-text-field 
                        v-model="fmSearch" 
                        prepend-inner-icon="mdi-magnify" 
                        label="Filter files..." 
                        density="compact" 
                        variant="outlined" 
                        hide-details 
                        bg-color="#121212" 
                        class="flex-grow-1 flex-sm-grow-0"
                        style="min-width: 150px; max-width: 200px;"
                    ></v-text-field>
                    
                    <v-select 
                        v-model="currentFolder" 
                        :items="folderList" 
                        item-title="label" 
                        item-value="path" 
                        density="compact" 
                        variant="outlined" 
                        hide-details 
                        bg-color="#121212" 
                        class="flex-grow-1 flex-sm-grow-0"
                        style="min-width: 150px; max-width: 250px;" 
                        @update:model-value="loadFiles"
                    ></v-select>
                </div>
            </v-card-title>

            <v-card-text class="pa-0" style="height: 500px;">
                <v-data-table 
                    v-model="selectedFiles" 
                    show-select 
                    :headers="fmHeaders" 
                    :items="fileList" 
                    :search="fmSearch"
                    density="compact" 
                    item-value="name" 
                    class="bg-transparent" 
                    fixed-header 
                    height="100%" 
                    hover 
                    items-per-page="-1"
                >
                    <template #item.name="{ item }"><span class="text-no-wrap">{{ getRaw(item).name }}</span></template>
                    <template #item.type="{ item }">
                        <div class="d-flex align-center justify-end">
                            <v-chip v-if="getRaw(item).is_multi" size="x-small" color="orange" variant="outlined" class="mr-2" style="height: 18px; font-size: 10px;">Multi</v-chip>
                            <span class="text-caption text-grey text-no-wrap">{{ getRaw(item).type }}</span>
                        </div>
                    </template>
                    <template #bottom></template>
                </v-data-table>
            </v-card-text>
            <v-divider></v-divider>
            <v-card-actions class="bg-[#252525] d-flex flex-wrap align-center justify-end ga-2 pa-3">
                <v-file-input ref="fileInput" v-model="uploadFiles" multiple hide-input style="display:none" @update:modelValue="uploadSubtitles"></v-file-input>
                <v-btn color="blue" prepend-icon="mdi-upload" variant="text" @click="$refs.fileInput.click()" class="mr-auto">Upload Subs</v-btn>
                <v-btn color="warning" variant="text" prepend-icon="mdi-format-list-checks" @click="runRename">Align Names</v-btn>
                <v-btn color="error" variant="text" prepend-icon="mdi-delete" @click="runDelete" :disabled="selectedFiles.length === 0">Delete {{ selectedFiles.length > 0 ? `(${selectedFiles.length})` : '' }}</v-btn>
                <v-btn color="red" variant="tonal" prepend-icon="mdi-folder-remove" @click="runPurge">Purge Folder</v-btn>
                <v-btn variant="plain" prepend-icon="mdi-close" @click="fmDialog = false">Close</v-btn>
            </v-card-actions>
        </v-card>
      </v-dialog>
      
      <v-dialog v-model="detailsDialog" max-width="1000px" scrollable>
        <v-card color="#1E1E1E">
            <v-card-title class="d-flex align-center border-b border-grey-darken-3 bg-[#252525]">
                <v-icon start color="warning">mdi-movie-open</v-icon> {{ selectedMedia?.name }}
                <v-spacer></v-spacer>
                <v-btn icon="mdi-close" variant="text" size="small" @click="detailsDialog = false"></v-btn>
            </v-card-title>
            <v-card-text class="pa-4 bg-[#121212]" style="max-height: 70vh;">
                <div v-if="!detailData || !detailData.seasons || detailData.seasons.length === 0" class="text-center text-grey py-8">No details.</div>
                <div v-else>
                    <div v-for="(season, i) in detailData.seasons" :key="i" class="mb-2">
                        <div 
                          v-if="detailData.info.type !== 'movie'"
                          class="d-flex align-center cursor-pointer pa-2 rounded hover-bg"
                          @click="season.expanded = !season.expanded"
                        >
                            <v-icon :class="{'rotate-90': season.expanded}" class="transition-transform mr-2" size="small">mdi-chevron-right</v-icon>
                            <div class="text-subtitle-2 font-weight-bold text-primary">{{ season.season }}</div>
                            <v-chip size="x-small" :color="season.okCount === season.totalCount ? 'green' : 'grey'" variant="outlined" class="font-weight-bold ml-2">
                                {{ season.okCount }} / {{ season.totalCount }}
                            </v-chip>
                        </div>

                        <v-expand-transition>
                            <div 
                              v-show="season.expanded" 
                              :class="detailData.info.type !== 'movie' ? 'ml-4 pl-2 border-l border-grey-darken-3' : ''"
                            >
                                <v-card v-for="(ep, j) in season.episodes" :key="j" variant="flat" color="transparent" class="mb-1 py-1">
                                    <div class="d-flex align-center px-2">
                                        <v-icon :color="ep.status === 'ok' ? 'green' : 'red'" size="small" class="mr-3">{{ ep.status === 'ok' ? 'mdi-check-circle' : 'mdi-alert-circle' }}</v-icon>
                                        <div class="flex-grow-1" style="min-width: 0;">
                                            <div class="text-body-2 font-weight-medium text-truncate text-grey-lighten-1">{{ ep.name }}</div>
                                            
                                            <div class="d-flex flex-wrap gap-1 mt-1" v-if="ep.media_info && !ep.media_info.error">
                                                <v-chip size="x-small" color="blue-grey" variant="tonal" class="info-badge" v-if="ep.media_info.Duration">⏱ {{ ep.media_info.Duration }}</v-chip>
                                                <v-chip size="x-small" color="indigo" variant="tonal" class="info-badge">{{ ep.media_info.Resolution }}</v-chip>
                                                <v-chip size="x-small" color="deep-purple" variant="tonal" class="info-badge" v-if="ep.media_info['Video Codec']">{{ ep.media_info['Video Codec'] }}</v-chip>
                                                <v-chip size="x-small" color="teal" variant="tonal" class="info-badge" v-if="ep.media_info['Frame Rate'] !== 'N/A'">{{ ep.media_info['Frame Rate'] }}</v-chip>
                                                <v-chip size="x-small" color="cyan" variant="tonal" class="info-badge" v-if="ep.media_info['Bit Depth']">{{ ep.media_info['Bit Depth'] }}</v-chip>
                                                <v-chip size="x-small" v-if="ep.media_info['Video Dynamic Range'] !== 'SDR'" color="purple" variant="tonal" class="info-badge">{{ ep.media_info['Video Dynamic Range'] }}</v-chip>
                                                <v-chip size="x-small" color="orange" variant="tonal" class="info-badge" v-if="ep.media_info['Audio Codec']">{{ ep.media_info['Audio Codec'] }}</v-chip>
                                                <span class="text-caption text-grey ml-2 mono-font align-self-center">{{ ep.media_info.Size }}</span>
                                            </div>

                                            <div class="d-flex align-center mt-1" v-if="ep.detail">
                                                <v-icon size="x-small" class="mr-1" color="grey">mdi-subtitles</v-icon>
                                                <v-chip v-if="ep.detail.includes('[外部]')" size="x-small" color="amber" label variant="flat" class="mr-1 px-1 font-weight-bold" style="height:16px; font-size: 10px;">EXT</v-chip>
                                                <v-chip v-if="ep.detail.includes('[內嵌]')" size="x-small" color="blue-grey" label variant="flat" class="mr-1 px-1 font-weight-bold" style="height:16px; font-size: 10px;">EMB</v-chip>
                                                <span class="text-caption text-grey-lighten-1 text-wrap" style="word-break: break-word;">{{ ep.detail.replace('[外部]', '').replace('[內嵌]', '').trim() }}</span>
                                            </div>

                                        </div>
                                    </div>
                                </v-card>
                            </div>
                        </v-expand-transition>
                    </div>
                </div>
            </v-card-text>
        </v-card>
      </v-dialog>

    <v-snackbar v-model="snackbar" :timeout="3000" color="grey-darken-3">{{ snackbarText }}<template v-slot:actions><v-btn color="white" variant="text" @click="snackbar = false">Close</v-btn></template></v-snackbar>
    </v-main>
  </v-app>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, onUnmounted, computed } from 'vue'
import { useDisplay } from 'vuetify'
import axios from 'axios'

const { mobile } = useDisplay()

const drawer = ref(true); 
const rail = ref(true); 
const currentView = ref('media'); 
const config = ref({}); 
const status = reactive({ 
    space: { free: '?', total: '?' }, 
    scan: { last: '...', next: '...', running: false },
    sync: { last: '...', next: '...', running: false }
}); 
const checkingSpace = ref(false); const snackbar = ref(false); const snackbarText = ref('')
const showMsg = (msg) => { console.log(`[UI] ${msg}`); snackbarText.value = msg; snackbar.value = true }
const syncRunning = ref(false); const syncData = reactive({ speed: '0 B/s', eta: '-', total: '0 / 0', progress: 0, files: {} }); const logContent = ref(""); const logBox = ref(null); let logPoller = null; let statusPoller = null;
const search = ref(''); const mediaList = ref([])
const mediaHeaders = [ 
    { title: 'Type', key: 'type', width: '80px', sortable: true }, 
    { title: 'Drive', key: 'drive', width: '100px', sortable: true },
    { title: 'Status', key: 'status', width: '80px', sortable: true }, 
    { title: 'Ver.', key: 'is_multi', align: 'center', width: '80px', sortable: true }, 
    { title: 'Name', key: 'name', sortable: true }, 
    { title: 'Actions', key: 'actions', align: 'end', sortable: false, width: '130px' } 
]
const fmHeaders = [ { title: 'Name', key: 'name', align: 'start', sortable: true }, { title: 'Type', key: 'type', width: '120px', align: 'end', sortable: true } ]
const getRaw = (item) => item && item.raw ? item.raw : item
const fmDialog = ref(false); const detailsDialog = ref(false); const selectedMedia = ref(null); const detailData = ref(null); const folderList = ref([]); const currentFolder = ref(''); const fileList = ref([]); const selectedFiles = ref([]); const uploadFiles = ref([])

const scanTarget = ref("All")
const scanOptions = ref(["All"])

const fmSearch = ref('')

const autoScrollPaused = ref(false)
let logPauseTimer = null

axios.defaults.baseURL = '/'
const fetchConfig = async () => { try { const r = await axios.get('api/config'); config.value = r.data } catch(e){ console.error(e) } }
const saveConfig = async () => { try { await axios.post('api/config', config.value); showMsg('Settings Saved'); await fetchConfig(); await fetchStatus() } catch(e) { showMsg('Error'); console.error(e) } }
const fetchStatus = async (force=false) => { if(force) checkingSpace.value=true; try { const r = await axios.get(`api/status?refresh_space=${force}`); Object.assign(status, r.data); if(force) showMsg('Space Updated') } catch(e){ console.error(e) } finally { checkingSpace.value = false } }
const fetchLogs = async () => { try { const r = await axios.get('api/logs'); logContent.value = r.data.logs.join(''); nextTick(() => { if(!autoScrollPaused.value && logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight }) } catch(e) {} }
const startLogPolling = () => { stopLogPolling(); fetchLogs(); logPoller = setInterval(fetchLogs, 2000) }
const stopLogPolling = () => { if (logPoller) clearInterval(logPoller); logPoller = null }

const changeView = (view) => { 
    currentView.value = view
    if (mobile.value) {
        drawer.value = false
    }
}

const scrollToBottom = () => {
    if (logBox.value) {
        logBox.value.scrollTop = logBox.value.scrollHeight
    }
}

const handleLogUserInteraction = () => {
    autoScrollPaused.value = true
    if (logPauseTimer) clearTimeout(logPauseTimer)
    logPauseTimer = setTimeout(() => {
        autoScrollPaused.value = false
        scrollToBottom()
    }, 10000)
}

watch(currentView, (newVal) => { if (newVal === 'logs') startLogPolling(); else stopLogPolling() })
const startSync = () => { if (ws && ws.readyState === 1) { ws.send("start_sync"); showMsg('Sync Started') } else showMsg('WS Disconnected') }
const stopSync = async () => { try { await axios.post('api/sync/stop'); showMsg('Sync Stopped'); await fetchConfig(); } catch(e){ console.error(e) } }

const startScan = async () => { 
    try { 
        let target = null;
        if (scanTarget.value !== "All") {
            const root = config.value.path || "/Cloud";
            target = `${root}/${scanTarget.value}`.replace('//', '/');
        } else {
            target = config.value.path || "/Cloud";
        }
        
        await axios.post('api/scan', null, { params: { target } }); 
        showMsg(`Scan Started: ${scanTarget.value}`) 
    } catch(e){ 
        showMsg('Error'); console.error(e) 
    } 
}

// [新增] 產生 STRM 的功能
const generateStrm = async () => { 
    showMsg('Generating STRM files...'); 
    try { 
        const r = await axios.post('api/strm/generate'); 
        showMsg(`Success! Generated ${r.data.count} STRM files to ${r.data.path}`); 
    } catch(e) { 
        showMsg('Error generating STRM'); 
        console.error(e); 
    } 
}

const loadMedia = async () => { try { const r = await axios.get('api/media'); mediaList.value = r.data } catch(e){ mediaList.value=[] } }
const clearDB = async () => { if(confirm('Clear DB?')) { try { await axios.post('api/media/clear'); showMsg('Cleared'); await loadMedia() } catch(e){ console.error(e) } } }
const refreshItem = async (data) => { if(data){ showMsg(`Refreshing: ${data.name}...`); try { await axios.post(`api/media/${data.id}/refresh`); showMsg(`Refreshed: ${data.name}`); await loadMedia() } catch(e){ showMsg('Error') } } }
const openDetails = async (data) => { 
    if(data){ 
        selectedMedia.value=data
        try { 
            const r = await axios.get(`api/media/${data.id}`)
            if(r.data.seasons) {
                const isMovie = r.data.info.type === 'movie'
                r.data.seasons.forEach(s => {
                    s.expanded = isMovie 
                    s.totalCount = s.episodes.length
                    s.okCount = s.episodes.filter(e => e.status === 'ok').length
                })
            }
            detailData.value = r.data
            detailsDialog.value=true 
        } catch(e) {} 
    } 
}
const openFileManager = async (data) => { 
    if(data){ 
        selectedMedia.value=data; 
        fmSearch.value = ''; 
        try { 
            const r = await axios.get(`api/media/${data.id}/folders`); 
            folderList.value=r.data; 
            if(folderList.value.length>0){ 
                currentFolder.value=folderList.value[0].path; 
                loadFiles() 
            }; 
            fmDialog.value=true 
        } catch(e) {} 
    } 
}
const loadFiles = async () => { try { const r = await axios.get(`api/files?path=${encodeURIComponent(currentFolder.value)}`); fileList.value=r.data; selectedFiles.value=[] } catch(e){ fileList.value=[] } }
const runDelete = async () => { if(confirm('Delete?')){ showMsg('Deleting...'); try { await axios.post('api/media/delete', {media_id:selectedMedia.value.id, folder_path:currentFolder.value, files:selectedFiles.value}); showMsg('Deleted'); loadFiles(); await loadMedia() } catch(e){ showMsg('Error') } } }
const runRename = async () => { showMsg('Renaming...'); try { await axios.post('api/media/rename', {media_id:selectedMedia.value.id, folder_path:currentFolder.value}); showMsg('Renamed'); loadFiles(); await loadMedia() } catch(e){ showMsg('Error') } }
const runPurge = async () => { if(confirm('Purge?')){ showMsg('Purging...'); try { const sk = folderList.value.find(f=>f.path===currentFolder.value)?.label; await axios.post('api/media/purge', {media_id:selectedMedia.value.id, folder_path:currentFolder.value, season_key:sk}); showMsg('Purged'); fmDialog.value=false; loadMedia() } catch(e){ showMsg('Error') } } }
const uploadSubtitles = async (files) => { if (!files || files.length === 0) return; const formData = new FormData(); formData.append('media_id', selectedMedia.value.id); formData.append('folder_path', currentFolder.value); for (let i = 0; i < files.length; i++) { formData.append('files', files[i]) }; showMsg(`Uploading...`); try { await axios.post('api/media/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } }); showMsg('Upload Success'); uploadFiles.value = []; loadFiles(); await loadMedia() } catch (e) { showMsg('Upload Failed'); console.error(e) } }

const formatTime = (ts) => { if (!ts) return 'Never'; const d = new Date(ts * 1000); return d.toLocaleString('zh-TW', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12: false}) }

let ws = null
const connectWs = () => {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${protocol}//${location.host}/ws/sync`)
    ws.onmessage = (e) => {
        const d = JSON.parse(e.data)
        if(d.type==='update'){ syncRunning.value=d.running; Object.assign(syncData, d.data); syncData.files=d.files }
        else if(d.type==='log'){ 
            if(currentView.value === 'logs') {
                logContent.value += d.msg + '\n'
                nextTick(() => { 
                    if (!autoScrollPaused.value) scrollToBottom() 
                })
            }
        }
        else if(d.type==='refresh_space'){ fetchStatus(true); showMsg('Sync Finished'); fetchConfig() }
    }
    ws.onclose = () => setTimeout(connectWs, 2000)
}

const fetchDrives = async () => {
    try {
        const r = await axios.get('api/drives');
        if (Array.isArray(r.data)) {
            scanOptions.value = ["All", ...r.data];
        } else {
            scanOptions.value = ["All"];
        }
    } catch (e) {
        scanOptions.value = ["All"];
    }
}

watch(() => config.value.path, async (newPath) => {
    if (newPath) fetchDrives();
});

watch(() => status.scan.running, (newVal, oldVal) => {
    if (oldVal === true && newVal === false) {
        showMsg('Library Scan Finished');
        loadMedia();
    }
});

onMounted(() => { 
    if (mobile.value) {
        drawer.value = false;
    }

    fetchConfig(); 
    fetchDrives(); 
    fetchStatus(); 
    loadMedia(); 
    connectWs(); 
    if (currentView.value === 'logs') startLogPolling();
    
    statusPoller = setInterval(() => {
        fetchStatus();
    }, 3000);
})

onUnmounted(() => {
    stopLogPolling();
    if (statusPoller) clearInterval(statusPoller);
})
</script>

<style>
/* ... existing styles ... */
html, body { overflow: hidden; height: 100%; margin: 0; background: #121212; }
#app { height: 100%; }
.v-application { height: 100%; display: flex; flex-direction: column; }
.v-main { height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
.mono-font { font-family: 'Roboto Mono', monospace; }
.sticky-header-table .v-data-table__th { background: #1E1E1E !important; white-space: nowrap; z-index: 10; }
.info-badge { font-size: 10px; font-weight: bold; border: 1px solid rgba(255,255,255,0.2); }
.fade-transition { transition: opacity 0.2s ease-in-out; }
.rotate-90 { transform: rotate(90deg); }
.transition-transform { transition: transform 0.2s; }
.cursor-pointer { cursor: pointer; }
.hover-bg:hover { background-color: rgba(255,255,255,0.05); }

@media (max-width: 600px) {
  .hidden-xs { display: none !important; }
}
</style>