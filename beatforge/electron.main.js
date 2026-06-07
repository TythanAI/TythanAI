const { app, BrowserWindow, dialog, Menu, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')

const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged

function createWindow() {
  const win = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    backgroundColor: '#0f0f0f',
    titleBarStyle: 'hidden',
    frame: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'electron.preload.js')
    }
  })

  if (isDev) {
    win.loadURL('http://localhost:5173')
    win.webContents.openDevTools({ mode: 'detach' })
  } else {
    win.loadFile(path.join(__dirname, 'dist/index.html'))
  }

  const menu = Menu.buildFromTemplate([
    {
      label: 'File',
      submenu: [
        { label: 'New Project', accelerator: 'CmdOrCtrl+N', click: () => win.webContents.send('menu-new') },
        { label: 'Open Project...', accelerator: 'CmdOrCtrl+O', click: async () => {
          const { canceled, filePaths } = await dialog.showOpenDialog({ filters: [{ name: 'BEATFORGE', extensions: ['bdaw'] }] })
          if (!canceled) win.webContents.send('menu-open', filePaths[0])
        }},
        { label: 'Save Project', accelerator: 'CmdOrCtrl+S', click: () => win.webContents.send('menu-save') },
        { label: 'Save As...', accelerator: 'CmdOrCtrl+Shift+S', click: async () => {
          const { canceled, filePath } = await dialog.showSaveDialog({ filters: [{ name: 'BEATFORGE', extensions: ['bdaw'] }] })
          if (!canceled) win.webContents.send('menu-save-as', filePath)
        }},
        { type: 'separator' },
        { label: 'Export WAV...', click: () => win.webContents.send('menu-export-wav') },
        { type: 'separator' },
        { role: 'quit' }
      ]
    },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }] }
  ])
  Menu.setApplicationMenu(menu)
}

ipcMain.handle('save-file', async (_, { filePath, data }) => {
  fs.writeFileSync(filePath, data, 'utf8')
  return { ok: true }
})

ipcMain.handle('read-file', async (_, filePath) => {
  return fs.readFileSync(filePath, 'utf8')
})

ipcMain.handle('show-save-dialog', async (_, opts) => {
  return dialog.showSaveDialog(opts)
})

ipcMain.handle('show-open-dialog', async (_, opts) => {
  return dialog.showOpenDialog(opts)
})

app.whenReady().then(createWindow)
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
