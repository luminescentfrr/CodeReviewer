/**
 * main.js — Electron main process entry point
 *
 * Responsibilities:
 * 1. Create the BrowserWindow (VS Code-like, frameless with custom title bar)
 * 2. Spawn Python FastAPI backend as a child process
 * 3. Health-check the backend until ready, then load the frontend
 * 4. Register IPC handlers for file system + window controls
 * 5. Gracefully shut down Python on app quit
 */

const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');
const { registerFileHandlers } = require('./file-service');

// ── Configuration ─────────────────────────────────────────────────────────

const DEFAULT_PYTHON_PORT = 8765;
const PYTHON_HOST = '127.0.0.1';
const PROJECT_ROOT = path.join(__dirname, '..');
const FRONTEND_PATH = path.join(PROJECT_ROOT, 'frontend', 'index.html');
const HEALTH_CHECK_INTERVAL_MS = 500;
const HEALTH_CHECK_TIMEOUT_MS = 30000;

let mainWindow = null;
let pythonProcess = null;
let pythonPort = DEFAULT_PYTHON_PORT;
let backendUrl = `http://${PYTHON_HOST}:${pythonPort}`;

// ── Window Creation ───────────────────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    frame: false,                    // Frameless for custom title bar
    titleBarStyle: 'hidden',
    backgroundColor: '#0d1117',      // Dark background to avoid white flash
    icon: path.join(PROJECT_ROOT, 'frontend', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  // Register file system IPC handlers
  registerFileHandlers(mainWindow);

  // Navigation restrictions
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('file://')) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.on('will-attach-webview', (event) => {
    event.preventDefault();
  });

  // Register window control IPC handlers
  ipcMain.on('win-minimize', () => mainWindow?.minimize());
  ipcMain.on('win-maximize', () => {
    if (mainWindow?.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow?.maximize();
    }
  });
  ipcMain.on('win-close', () => mainWindow?.close());

  // Build application menu
  const menu = Menu.buildFromTemplate([
    {
      label: '文件',
      submenu: [
        {
          label: '打开目录...',
          accelerator: 'CmdOrCtrl+O',
          click: async () => {
            // Trigger the open-folder flow directly
            mainWindow.webContents.send('menu-open-folder');
          },
        },
        {
          label: '打开文件...',
          accelerator: 'CmdOrCtrl+Shift+O',
          click: () => {
            mainWindow.webContents.send('menu-open-file');
          },
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: 'CmdOrCtrl+Q',
          click: () => app.quit(),
        },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload', label: '重新载入' },
        { role: 'forceReload', label: '强制重新载入' },
        { role: 'toggleDevTools', label: '开发者工具' },
        { type: 'separator' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { role: 'resetZoom', label: '重置缩放' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 CodeReview AI',
          click: () => {
            const { dialog } = require('electron');
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: '关于 CodeReview AI',
              message: 'CodeReview AI v1.0.0',
              detail: '多智能体 AI 代码审查桌面应用\n\n基于 LangGraph + DeepSeek/OpenAI\n6 个审查智能体 + 自动修复',
            });
          },
        },
      ],
    },
  ]);
  Menu.setApplicationMenu(menu);

  return mainWindow;
}

// ── Python Backend Management ─────────────────────────────────────────────

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => {
      server.close(() => resolve(true));
    });
    server.listen(port, PYTHON_HOST);
  });
}

async function pickBackendPort() {
  for (let port = DEFAULT_PYTHON_PORT; port < DEFAULT_PYTHON_PORT + 20; port += 1) {
    if (await isPortAvailable(port)) {
      return port;
    }
  }
  throw new Error(`No available backend port found near ${DEFAULT_PYTHON_PORT}`);
}

/**
 * Load the Python interpreter path from electron/config.json.
 * Priority: CODEREVIEW_PYTHON env var > config.json > system "python"
 */
function resolvePythonPath() {
  // 1. Environment variable (highest priority)
  if (process.env.CODEREVIEW_PYTHON) {
    console.log('[Main] Using Python from CODEREVIEW_PYTHON env var');
    return process.env.CODEREVIEW_PYTHON;
  }

  // 2. Config file
  const configPath = path.join(__dirname, 'config.json');
  try {
    if (fs.existsSync(configPath)) {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      if (config.pythonPath) {
        console.log('[Main] Using Python from electron/config.json');
        return config.pythonPath;
      }
    }
  } catch (e) {
    console.warn('[Main] Failed to read config.json:', e.message);
  }

  // 3. System fallback
  console.log('[Main] Using system Python');
  return 'python';
}

async function startPythonBackend() {
  console.log('[Main] Starting Python backend...');

  pythonPort = await pickBackendPort();
  backendUrl = `http://${PYTHON_HOST}:${pythonPort}`;
  if (pythonPort !== DEFAULT_PYTHON_PORT) {
    console.log(`[Main] Port ${DEFAULT_PYTHON_PORT} is busy; using ${pythonPort} instead.`);
  }

  const pythonCmd = resolvePythonPath();

  pythonProcess = spawn(pythonCmd, [
    '-m', 'uvicorn',
    'backend.main:app',
    '--host', PYTHON_HOST,
    '--port', String(pythonPort),
    '--log-level', 'info',
  ], {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  pythonProcess.stdout.on('data', (data) => {
    const msg = data.toString().trim();
    console.log(`[Python] ${msg}`);
    if (mainWindow) {
      mainWindow.webContents.send('backend-log', { level: 'info', message: msg });
    }
  });

  pythonProcess.stderr.on('data', (data) => {
    const msg = data.toString().trim();
    // uvicorn logs to stderr by default; not necessarily an error
    console.log(`[Python] ${msg}`);
    if (mainWindow) {
      mainWindow.webContents.send('backend-log', { level: 'info', message: msg });
    }
  });

  pythonProcess.on('error', (err) => {
    console.error('[Main] Failed to start Python backend:', err.message);
    if (mainWindow) {
      mainWindow.webContents.send('backend-error', {
        message: `无法启动 Python 后端: ${err.message}\n请确保已安装 Python 3.10+ 和 pip 依赖`,
      });
    }
  });

  pythonProcess.on('exit', (code, signal) => {
    console.log(`[Main] Python backend exited (code=${code}, signal=${signal})`);
    pythonProcess = null;
  });
}

/**
 * Poll the health endpoint until the backend is ready
 */
function waitForBackend() {
  return new Promise((resolve, reject) => {
    const startTime = Date.now();

    const check = () => {
      const req = http.get(`${backendUrl}/api/health`, (res) => {
        let body = '';
        res.on('data', (chunk) => body += chunk);
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            if (data.status === 'ok') {
              console.log('[Main] Python backend is ready!');
              resolve(data);
              return;
            }
          } catch {}
          scheduleRetry();
        });
      });

      req.on('error', () => {
        scheduleRetry();
      });

      req.setTimeout(2000, () => {
        req.destroy();
        scheduleRetry();
      });
    };

    const scheduleRetry = () => {
      if (Date.now() - startTime > HEALTH_CHECK_TIMEOUT_MS) {
        reject(new Error('Backend health check timed out after 30s'));
        return;
      }
      setTimeout(check, HEALTH_CHECK_INTERVAL_MS);
    };

    check();
  });
}

function stopPythonBackend() {
  if (pythonProcess) {
    console.log('[Main] Stopping Python backend...');
    if (process.platform === 'win32') {
      // On Windows, use taskkill to terminate the process tree
      spawn('taskkill', ['/pid', String(pythonProcess.pid), '/f', '/t']);
    } else {
      pythonProcess.kill('SIGTERM');
    }
    pythonProcess = null;
  }
}

// ── App Lifecycle ─────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  const win = createWindow();

  // Show a loading state while waiting for backend
  // Load the frontend immediately — it will show a loading indicator
  win.loadFile(FRONTEND_PATH);

  try {
    // Start Python backend after the window exists so startup errors can be shown.
    await startPythonBackend();
    const health = await waitForBackend();
    win.webContents.send('backend-ready', {
      provider: health.primary_provider || 'unknown',
      configured: health.llm_configured || false,
      url: backendUrl,
      port: pythonPort,
    });
  } catch (err) {
    console.error('[Main] Backend failed to start:', err.message);
    win.webContents.send('backend-error', {
      message: err.message,
    });
  }
});

app.on('before-quit', () => {
  stopPythonBackend();
});

app.on('window-all-closed', () => {
  stopPythonBackend();
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});
