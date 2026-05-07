/**
 * file-service.js — File system operations for Electron IPC
 *
 * Provides directory tree scanning, file read/write, and native dialog
 * wrappers. Registered as IPC handlers in main process.
 */

const { ipcMain, dialog } = require('electron');
const fs = require('fs');
const path = require('path');

// Directories and files to exclude from tree scanning
const EXCLUDED_NAMES = new Set([
  'node_modules', '.git', '__pycache__', '.venv', 'venv',
  '.env', '.DS_Store', 'Thumbs.db', '.idea', '.vscode',
  'dist', 'build', '.next', '.cache', '.tox', '.mypy_cache',
  '.pytest_cache', 'egg-info', '*.pyc', '*.pyo',
]);

// File extensions recognized as code files
const CODE_EXTENSIONS = new Set([
  '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c',
  '.h', '.hpp', '.go', '.rs', '.rb', '.php', '.cs', '.swift',
  '.kt', '.scala', '.vue', '.svelte', '.html', '.css', '.scss',
  '.json', '.yaml', '.yml', '.toml', '.md', '.txt', '.sh',
  '.bat', '.ps1', '.sql', '.r', '.m', '.lua', '.dart',
]);

// Map file extension to language identifier
const EXT_TO_LANG = {
  '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
  '.jsx': 'javascript', '.tsx': 'typescript', '.java': 'java',
  '.cpp': 'cpp', '.c': 'cpp', '.h': 'cpp', '.hpp': 'cpp',
  '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
  '.cs': 'csharp', '.swift': 'swift', '.kt': 'kotlin',
};

/**
 * Check if a name should be excluded from file tree scan
 */
function shouldExclude(name) {
  if (EXCLUDED_NAMES.has(name)) return true;
  if (name.startsWith('.') && name !== '.env.example') return true;
  return false;
}

/**
 * Recursively build a file tree structure from a directory
 * @param {string} dirPath - Absolute path to the directory
 * @param {number} depth - Current depth (max 8 levels)
 * @returns {Array} Tree nodes: [{name, path, type:'file'|'dir', children?, ext?}]
 */
function buildFileTree(dirPath, depth = 0) {
  if (depth > 8) return [];

  let entries;
  try {
    entries = fs.readdirSync(dirPath, { withFileTypes: true });
  } catch (err) {
    return [];
  }

  const nodes = [];

  // Sort: directories first, then files, alphabetical within each group
  const dirs = entries.filter(e => e.isDirectory() && !shouldExclude(e.name));
  const files = entries.filter(e => e.isFile() && !shouldExclude(e.name));
  dirs.sort((a, b) => a.name.localeCompare(b.name));
  files.sort((a, b) => a.name.localeCompare(b.name));

  for (const dir of dirs) {
    const fullPath = path.join(dirPath, dir.name);
    nodes.push({
      name: dir.name,
      path: fullPath,
      type: 'dir',
      children: buildFileTree(fullPath, depth + 1),
    });
  }

  for (const file of files) {
    const fullPath = path.join(dirPath, file.name);
    const ext = path.extname(file.name).toLowerCase();
    nodes.push({
      name: file.name,
      path: fullPath,
      type: 'file',
      ext: ext,
      isCode: CODE_EXTENSIONS.has(ext),
      language: EXT_TO_LANG[ext] || null,
    });
  }

  return nodes;
}

// Project root for path validation (set on first file operation)
let _projectRoot = null;

/**
 * Validate a file path is within the project root directory.
 * Throws an error if path traversal is detected.
 */
function validatePath(filePath) {
  const resolved = path.resolve(filePath);
  if (_projectRoot) {
    const root = path.resolve(_projectRoot);
    if (!resolved.startsWith(root)) {
      throw new Error(`Path traversal denied: ${filePath} is outside project root`);
    }
  }
  return resolved;
}

function setProjectRoot(rootPath) {
  _projectRoot = rootPath;
}

/**
 * Register all file-service IPC handlers
 * @param {BrowserWindow} mainWindow - Reference to the main window
 */
function registerFileHandlers(mainWindow) {

  // Open folder dialog — returns {canceled, rootPath, tree}
  ipcMain.handle('open-folder', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory'],
      title: '打开项目目录',
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true };
    }
    const rootPath = result.filePaths[0];
    setProjectRoot(rootPath);
    const tree = buildFileTree(rootPath);
    return { canceled: false, rootPath, tree };
  });

  // Open file(s) dialog — returns {canceled, files: [{path, name, content, language}]}
  ipcMain.handle('open-file', async () => {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openFile', 'multiSelections'],
      title: '打开文件',
      filters: [
        { name: '代码文件', extensions: ['py', 'js', 'ts', 'java', 'cpp', 'go', 'c', 'h', 'rs', 'rb'] },
        { name: '所有文件', extensions: ['*'] },
      ],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true };
    }
    const files = [];
    for (const filePath of result.filePaths) {
      try {
        const content = fs.readFileSync(filePath, 'utf-8');
        const ext = path.extname(filePath).toLowerCase();
        files.push({
          path: filePath,
          name: path.basename(filePath),
          content,
          language: EXT_TO_LANG[ext] || 'plaintext',
        });
      } catch (err) {
        console.error(`Failed to read file ${filePath}:`, err.message);
      }
    }
    return { canceled: false, files };
  });

  // Get file tree for a given root path
  ipcMain.handle('get-file-tree', (event, rootPath) => {
    if (!fs.existsSync(rootPath)) return [];
    return buildFileTree(rootPath);
  });

  // Read directory listing (shallow)
  ipcMain.handle('read-dir', (event, dirPath) => {
    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      return entries.map(e => ({
        name: e.name,
        type: e.isDirectory() ? 'dir' : 'file',
        path: path.join(dirPath, e.name),
      }));
    } catch (err) {
      return { error: err.message };
    }
  });

  // Read file content (UTF-8)
  ipcMain.handle('read-file', (event, filePath) => {
    try {
      const safePath = validatePath(filePath);
      const content = fs.readFileSync(safePath, 'utf-8');
      const ext = path.extname(filePath).toLowerCase();
      return {
        content,
        language: EXT_TO_LANG[ext] || 'plaintext',
        name: path.basename(filePath),
        path: filePath,
      };
    } catch (err) {
      return { error: err.message };
    }
  });

  // Write file content
  ipcMain.handle('write-file', (event, filePath, content) => {
    try {
      const safePath = validatePath(filePath);
      fs.writeFileSync(safePath, content, 'utf-8');
      return { success: true };
    } catch (err) {
      return { error: err.message };
    }
  });

  // Collect all code files in a directory for project review
  ipcMain.handle('collect-project-files', (event, rootPath, maxFiles = 50) => {
    const files = [];
    function walk(dir, depth = 0) {
      if (depth > 6 || files.length >= maxFiles) return;
      let entries;
      try { entries = fs.readdirSync(dir, { withFileTypes: true }); }
      catch { return; }
      for (const entry of entries) {
        if (shouldExclude(entry.name)) continue;
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          walk(fullPath, depth + 1);
        } else if (entry.isFile()) {
          const ext = path.extname(entry.name).toLowerCase();
          if (CODE_EXTENSIONS.has(ext) && files.length < maxFiles) {
            try {
              const stat = fs.statSync(fullPath);
              // Skip files larger than 100KB
              if (stat.size > 100 * 1024) continue;
              const content = fs.readFileSync(fullPath, 'utf-8');
              files.push({
                filename: path.relative(rootPath, fullPath).replace(/\\/g, '/'),
                path: fullPath,
                code: content,
                language: EXT_TO_LANG[ext] || 'plaintext',
                size: stat.size,
              });
            } catch { /* skip unreadable files */ }
          }
        }
      }
    }
    walk(rootPath);
    return files;
  });
}

module.exports = { registerFileHandlers, buildFileTree, EXT_TO_LANG, CODE_EXTENSIONS };
