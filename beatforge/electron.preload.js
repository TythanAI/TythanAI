const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  saveFile: (data) => ipcRenderer.invoke('save-file', data),
  readFile: (path) => ipcRenderer.invoke('read-file', path),
  showSaveDialog: (opts) => ipcRenderer.invoke('show-save-dialog', opts),
  showOpenDialog: (opts) => ipcRenderer.invoke('show-open-dialog', opts),
  onMenuNew: (cb) => ipcRenderer.on('menu-new', cb),
  onMenuOpen: (cb) => ipcRenderer.on('menu-open', (_, p) => cb(p)),
  onMenuSave: (cb) => ipcRenderer.on('menu-save', cb),
  onMenuSaveAs: (cb) => ipcRenderer.on('menu-save-as', (_, p) => cb(p)),
  onMenuExportWav: (cb) => ipcRenderer.on('menu-export-wav', cb),
})
