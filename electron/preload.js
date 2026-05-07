/**
 * preload.js — Electron preload script
 *
 * Exposes a secure IPC bridge (window.electronAPI) to the renderer process
 * using contextBridge. The renderer can call these methods to interact with
 * the main process (file system, window controls) without direct Node access.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {

  // ── File System Operations ──────────────────────────────────────────

  /** Open a native folder picker dialog; returns {canceled, rootPath, tree} */
  openFolder: () => ipcRenderer.invoke('open-folder'),

  /** Open a native file picker dialog; returns {canceled, files} */
  openFile: () => ipcRenderer.invoke('open-file'),

  /** Get recursive file tree from a root path */
  getFileTree: (rootPath) => ipcRenderer.invoke('get-file-tree', rootPath),

  /** Read directory listing (shallow) */
  readDir: (dirPath) => ipcRenderer.invoke('read-dir', dirPath),

  /** Read file content (UTF-8); returns {content, language, name, path} */
  readFile: (filePath) => ipcRenderer.invoke('read-file', filePath),

  /** Write content to a file; returns {success} or {error} */
  writeFile: (filePath, content) => ipcRenderer.invoke('write-file', filePath, content),

  /** Collect all code files in a project directory for review */
  collectProjectFiles: (rootPath, maxFiles) =>
    ipcRenderer.invoke('collect-project-files', rootPath, maxFiles),

  // ── Window Controls ─────────────────────────────────────────────────

  /** Minimize the application window */
  minimize: () => ipcRenderer.send('win-minimize'),

  /** Toggle maximize/restore the application window */
  maximize: () => ipcRenderer.send('win-maximize'),

  /** Close the application window */
  close: () => ipcRenderer.send('win-close'),

  // ── Python Backend Status ───────────────────────────────────────────

  /** Listen for backend ready event from main process */
  onBackendReady: (callback) =>
    ipcRenderer.on('backend-ready', (event, data) => callback(data)),

  /** Listen for backend error event from main process */
  onBackendError: (callback) =>
    ipcRenderer.on('backend-error', (event, data) => callback(data)),

  /** Listen for backend log output */
  onBackendLog: (callback) =>
    ipcRenderer.on('backend-log', (event, data) => callback(data)),
});
