"""
file_tool.py — Workspace File Reading Tool

Mirrors the Read / Glob / Grep tool interface used by Claude Code:
  read_file   — paginated line-numbered file reading (offset + limit)
  glob_files  — pattern-based file discovery, sorted by mtime
  grep_files  — regex content search with before/after context lines
  scan_workspace       — discover all reviewable source files in a directory
  read_workspace_files — load files as {filename, code, language} items
                         for direct use in ProjectReviewRequest
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path

from ..config import MAX_SCAN_FILES, MAX_FILE_SIZE_KB

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

DEFAULT_IGNORE: frozenset[str] = frozenset({
    ".git", ".svn", ".hg",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", ".next", "dist", "build", ".venv", "venv", "env",
    ".idea", ".vscode",
})

BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo", ".class",
    ".db", ".sqlite", ".sqlite3",
})

EXTENSION_LANGUAGE: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    ".java": "java",
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".cxx":  "cpp",
    ".c":    "c",
    ".go":   "go",
    ".rs":   "rust",
    ".rb":   "ruby",
    ".php":  "php",
    ".cs":   "csharp",
    ".kt":   "kotlin",
    ".swift":"swift",
    ".sh":   "bash",
    ".bash": "bash",
    ".zsh":  "bash",
    ".html": "html",
    ".css":  "css",
    ".scss": "css",
    ".yaml": "yaml",
    ".yml":  "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md":   "markdown",
    ".sql":  "sql",
}


def detect_language(path: str) -> str:
    """Auto-detect programming language from file extension."""
    return EXTENSION_LANGUAGE.get(Path(path).suffix.lower(), "plaintext")


def _validate_path(path: str, workspace_root: str) -> Path:
    """
    Resolve and validate a file path.
    - Absolute paths: resolved as-is (LLM reads files from scanned workspaces).
    - Relative paths: must stay within workspace_root (block ../ traversal).
    """
    p = Path(path)
    if p.is_absolute():
        return p.resolve()
    root = Path(workspace_root).resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: '{path}' resolves outside workspace"
        )
    return resolved


def _open_text(path: Path) -> str | None:
    """Try to open a text file — single read, multiple decode attempts."""
    try:
        raw_bytes = path.read_bytes()
    except Exception:
        return None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw_bytes.decode(enc, errors="replace")
        except Exception:
            continue
    return None


# ── read_file ──────────────────────────────────────────────────────────────

from .tool_registry import register  # noqa: E402


@register(
    name="read_file_v2",
    description="读取项目中的任意文件，返回带行号的代码内容。支持分页（offset/limit）。",
    parameters={
        "path": {"type": "string", "description": "文件路径（相对于项目根目录的路径）"},
        "offset": {"type": "integer", "description": "起始行（0-indexed），默认 0"},
        "limit": {"type": "integer", "description": "最多返回行数，默认 2000"},
    },
    required_params=["path"],
)
def _tool_read_file(path: str, offset: int = 0, limit: int = 2000,
                    workspace_root: str = ".") -> dict:
    return read_file(str(_validate_path(path, workspace_root)),
                     offset=offset, limit=limit)


def read_file(
    path: str,
    offset: int = 0,
    limit: int = 2000,
) -> dict:
    """
    Read a file with line-number prefix and offset/limit pagination.

    Mirrors the Claude Code Read tool: returns content as "N\\tline" strings
    so callers can navigate by line number.  For files larger than `limit`
    lines, set `offset` to read successive windows.

    Args:
        path:   Absolute or relative file path.
        offset: First line to read (0-indexed).  Default 0.
        limit:  Maximum lines to return.  Default 2000.

    Returns dict:
        path           — resolved absolute path
        content        — line-numbered text ("1\\tfoo\\n2\\tbar\\n…")
        lines          — raw lines without numbering (for code analysis)
        total_lines    — total line count of the file
        offset         — actual start line used
        returned_lines — how many lines are in `lines`
        truncated      — True when the file has more lines beyond this window
        language       — auto-detected language string
        size_bytes     — file size on disk
        error          — present only when something went wrong
    """
    abs_path = Path(path).resolve()

    if not abs_path.exists():
        return {"error": f"File not found: {abs_path}", "path": str(abs_path)}
    if not abs_path.is_file():
        return {"error": f"Not a file: {abs_path}", "path": str(abs_path)}
    if abs_path.suffix.lower() in BINARY_EXTENSIONS:
        return {"error": f"Binary file skipped: {abs_path}", "path": str(abs_path)}

    raw = _open_text(abs_path)
    if raw is None:
        return {"error": f"Could not decode file: {abs_path}", "path": str(abs_path)}

    all_lines   = raw.splitlines()
    total_lines = len(all_lines)
    start       = max(0, offset)
    end         = min(total_lines, start + limit)
    selected    = all_lines[start:end]

    # cat -n style: 1-indexed line numbers separated by a tab
    numbered = "\n".join(f"{start + i + 1}\t{line}" for i, line in enumerate(selected))

    return {
        "path":           str(abs_path),
        "content":        numbered,
        "lines":          selected,
        "total_lines":    total_lines,
        "offset":         start,
        "returned_lines": len(selected),
        "truncated":      end < total_lines,
        "language":       detect_language(str(abs_path)),
        "size_bytes":     abs_path.stat().st_size,
    }


# ── glob_files ─────────────────────────────────────────────────────────────

def glob_files(
    pattern: str,
    base_path: str = ".",
    ignore: frozenset[str] | None = None,
    sort_by_mtime: bool = True,
) -> dict:
    """
    Find files matching a glob pattern, sorted by modification time (newest first).

    Mirrors the Claude Code Glob tool.

    Args:
        pattern:      Glob pattern, e.g. "**/*.py" or "src/**/*.ts".
        base_path:    Root directory to search from.
        ignore:       Directory names to skip.
        sort_by_mtime: Sort results newest-first (default True).

    Returns dict:
        pattern   — the pattern that was searched
        base_path — resolved root
        matches   — list of {path, relative, size, mtime, language}
        total     — len(matches)
    """
    if ignore is None:
        ignore = DEFAULT_IGNORE

    base    = Path(base_path).resolve()
    matches = []

    try:
        for p in base.glob(pattern):
            if not p.is_file():
                continue
            parts = p.relative_to(base).parts
            if any(part in ignore for part in parts):
                continue
            if p.suffix.lower() in BINARY_EXTENSIONS:
                continue
            st = p.stat()
            matches.append({
                "path":     str(p),
                "relative": p.relative_to(base).as_posix(),
                "size":     st.st_size,
                "mtime":    st.st_mtime,
                "language": detect_language(str(p)),
            })
    except Exception as e:
        logger.error("glob_files failed (pattern=%s): %s", pattern, e)

    if sort_by_mtime:
        matches.sort(key=lambda x: x["mtime"], reverse=True)

    return {"pattern": pattern, "base_path": str(base), "matches": matches, "total": len(matches)}


# ── grep_files ─────────────────────────────────────────────────────────────

def grep_files(
    pattern: str,
    path: str = ".",
    file_glob: str = "*",
    context: int = 2,
    case_sensitive: bool = False,
    ignore: frozenset[str] | None = None,
    max_results: int = 250,
) -> dict:
    """
    Search file contents using a regex pattern with context lines.

    Mirrors the Claude Code Grep tool (ripgrep-style).

    Args:
        pattern:        Regex pattern to search for.
        path:           File or directory to search.
        file_glob:      Glob filter for filenames, e.g. "*.py".
        context:        Lines of context before/after each match.
        case_sensitive: Default False (case-insensitive).
        ignore:         Directory names to skip.
        max_results:    Hard cap on returned matches.

    Returns dict:
        pattern  — the pattern searched
        matches  — list of {path, line, content, context_before, context_after}
        total    — number of matches returned
        truncated — True if max_results was hit
        error    — present only on regex compile failure
    """
    if ignore is None:
        ignore = DEFAULT_IGNORE

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return {"error": f"Invalid regex: {e}", "pattern": pattern, "matches": [], "total": 0, "truncated": False}

    target = Path(path).resolve()
    files_to_search: list[Path] = []

    if target.is_file():
        files_to_search = [target]
    elif target.is_dir():
        for p in target.rglob(file_glob):
            if not p.is_file():
                continue
            parts = p.relative_to(target).parts
            if any(part in ignore for part in parts):
                continue
            if p.suffix.lower() in BINARY_EXTENSIONS:
                continue
            files_to_search.append(p)

    all_matches: list[dict] = []
    truncated = False

    for file_path in files_to_search:
        raw = _open_text(file_path)
        if raw is None:
            continue
        lines = raw.splitlines()

        for i, line in enumerate(lines):
            if not regex.search(line):
                continue

            before_start = max(0, i - context)
            after_end    = min(len(lines), i + context + 1)

            all_matches.append({
                "path":           str(file_path),
                "line":           i + 1,
                "content":        line,
                "context_before": lines[before_start:i],
                "context_after":  lines[i + 1:after_end],
            })

            if len(all_matches) >= max_results:
                truncated = True
                break

        if truncated:
            break

    return {
        "pattern":   pattern,
        "matches":   all_matches,
        "total":     len(all_matches),
        "truncated": truncated,
    }


# ── scan_workspace ─────────────────────────────────────────────────────────

def scan_workspace(
    root_path: str,
    ignore: frozenset[str] | None = None,
    max_files: int = MAX_SCAN_FILES,
    max_file_size_kb: int = MAX_FILE_SIZE_KB,
) -> dict:
    """
    Scan a workspace directory and return metadata for all reviewable source files.

    Does NOT load file contents — use read_workspace_files for that.

    Args:
        root_path:        Root directory to scan.
        ignore:           Directory/component names to skip.
        max_files:        Cap on returned files.
        max_file_size_kb: Skip files larger than this threshold.

    Returns dict:
        root          — resolved root path
        files         — list of {path, relative, language, size, lines}
        total_files   — len(files)
        total_lines   — sum of line counts
        languages     — {language: file_count}
        truncated     — True if max_files was hit
        error         — present only if root_path doesn't exist
    """
    if ignore is None:
        ignore = DEFAULT_IGNORE

    root = Path(root_path).resolve()
    if not root.exists():
        return {"error": f"Path does not exist: {root_path}", "files": []}

    max_bytes        = max_file_size_kb * 1024
    reviewable_exts  = frozenset(EXTENSION_LANGUAGE.keys())
    files: list[dict] = []
    language_counts: dict[str, int] = {}
    truncated = False

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts = p.relative_to(root).parts
        if any(part in ignore for part in parts):
            continue
        if p.suffix.lower() not in reviewable_exts:
            continue

        st = p.stat()
        if st.st_size > max_bytes:
            continue

        lang = detect_language(str(p))
        language_counts[lang] = language_counts.get(lang, 0) + 1

        # 用文件大小估算行数，避免为统计行数而读取完整文件
        line_count = st.st_size // 40

        files.append({
            "path":     str(p),
            "relative": p.relative_to(root).as_posix(),
            "language": lang,
            "size":     st.st_size,
            "lines":    line_count,
        })

        if len(files) >= max_files:
            truncated = True
            break

    return {
        "root":        str(root),
        "files":       files,
        "total_files": len(files),
        "total_lines": sum(f["lines"] for f in files),
        "languages":   language_counts,
        "truncated":   truncated,
    }


# ── read_workspace_files ───────────────────────────────────────────────────

def read_workspace_files(
    root_path: str,
    file_paths: list[str] | None = None,
    glob_pattern: str = "**/*.py",
    offset: int = 0,
    limit: int = 2000,
) -> list[dict]:
    """
    Load files from a workspace and return them as {filename, code, language}
    dicts — the exact shape expected by ProjectReviewRequest.files and
    context_analyzer.analyze_project.

    For large files the offset/limit window is applied uniformly; callers that
    need different windows per file should call read_file directly.

    Args:
        root_path:    Workspace root directory.
        file_paths:   Specific relative paths to load (skips glob when given).
        glob_pattern: Glob pattern used when file_paths is None.
        offset:       Line offset applied to every file.
        limit:        Max lines loaded per file.

    Returns:
        List of {filename, code, language} — skips files that cannot be read.
    """
    if file_paths:
        abs_paths = [str(Path(root_path) / p) for p in file_paths]
    else:
        result    = glob_files(glob_pattern, root_path)
        abs_paths = [m["path"] for m in result["matches"]]

    items = []
    for p in abs_paths:
        res = read_file(p, offset=offset, limit=limit)
        if "error" in res:
            logger.warning("Skipped %s: %s", p, res["error"])
            continue
        items.append({
            "filename": res["path"],
            "code":     "\n".join(res["lines"]),  # raw lines, no line-number prefix
            "language": res["language"],
        })
    return items


# ── undo stack (for replace_code rollback) ───────────────────────────────
# Each ToolRegistry instance owns its undo stack; direct callers can pass None.


def undo_last_change(_undo_stack: list | None = None) -> dict:
    """Undo the most recent replace_code or write_file operation."""
    stack = _undo_stack or _get_default_undo_stack()
    if not stack:
        return {"success": False, "error": "Nothing to undo"}
    abs_path, original_content = stack.pop()
    try:
        Path(abs_path).write_text(original_content, encoding="utf-8")
        return {"success": True, "message": f"Restored {abs_path}", "file": abs_path}
    except Exception as e:
        return {"success": False, "error": str(e), "file": abs_path}


# Module-level fallback for backwards compatibility (single-request scenarios)
_default_undo_stack: list[tuple[str, str]] = []

def _get_default_undo_stack() -> list:
    return _default_undo_stack


# ── replace_code ─────────────────────────────────────────────────────────

def replace_code(
    file_path: str,
    old_string: str,
    new_string: str,
    workspace_root: str = ".",
    dry_run: bool = False,
    _undo_stack: list | None = None,
) -> dict:
    """
    Exact string replacement in a file.  old_string must match exactly once.

    Mirrors the Claude Code Edit tool contract.  When old_string matches
    zero times the caller must broaden the search; when it matches more
    than once the caller must add more surrounding context to disambiguate.

    When dry_run=True, only validates uniqueness — does not write to disk.
    Returns line_number and the strings so the frontend can apply in-editor.
    """
    abs_path = Path(workspace_root) / file_path
    try:
        content = abs_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {abs_path}"}
    except Exception as e:
        return {"success": False, "error": f"Could not read {abs_path}: {e}"}

    count = content.count(old_string)
    if count == 0:
        return {
            "success": False,
            "error": "old_string not found in file. Check the exact whitespace/indentation.",
            "file": str(abs_path),
        }
    if count > 1:
        return {
            "success": False,
            "error": f"old_string matches {count} locations — it must be unique. Add more surrounding context lines.",
            "file": str(abs_path),
            "match_count": count,
        }

    pos = content.index(old_string)
    line_number = content[:pos].count('\n') + 1
    end_line = line_number + new_string.count('\n')

    if dry_run:
        return {
            "success": True, "message": "1 replacement validated (dry_run)",
            "file": str(abs_path), "line_number": line_number, "end_line": end_line,
            "old_string": old_string, "new_string": new_string,
        }

    stack = _undo_stack if _undo_stack is not None else _get_default_undo_stack()
    stack.append((str(abs_path), content))
    new_content = content.replace(old_string, new_string, 1)
    abs_path.write_text(new_content, encoding="utf-8")
    return {
        "success": True, "message": "1 replacement made", "file": str(abs_path),
        "line_number": line_number, "end_line": end_line,
        "old_string": old_string, "new_string": new_string,
    }


# ── insert_code ───────────────────────────────────────────────────────────

def insert_code(
    file_path: str,
    after_line: int,
    code: str,
    workspace_root: str = ".",
    dry_run: bool = False,
    _undo_stack: list | None = None,
) -> dict:
    """
    Insert new code after a given line number.  Used for adding missing
    functions, classes, or imports that have no existing code to match against.

    When dry_run=True, only validates the line number — does not write to disk.
    """
    abs_path = Path(workspace_root) / file_path
    try:
        content = abs_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"success": False, "error": f"File not found: {abs_path}"}
    except Exception as e:
        return {"success": False, "error": f"Could not read {abs_path}: {e}"}

    lines = content.split('\n')
    if after_line < 0 or after_line > len(lines):
        return {"success": False, "error": f"after_line {after_line} out of range (0–{len(lines)})"}

    if dry_run:
        return {
            "success": True, "message": "insert validated (dry_run)",
            "file": str(abs_path), "inserted_at_line": after_line + 1, "code": code,
        }

    stack = _undo_stack if _undo_stack is not None else _get_default_undo_stack()
    stack.append((str(abs_path), content))
    lines.insert(after_line, code)
    abs_path.write_text('\n'.join(lines), encoding="utf-8")
    return {
        "success": True, "message": f"Inserted at line {after_line + 1}",
        "file": str(abs_path), "inserted_at_line": after_line + 1, "code": code,
    }


# ── delete_file ───────────────────────────────────────────────────────────

def delete_file(
    file_path: str,
    workspace_root: str = ".",
    dry_run: bool = False,
    _undo_stack: list | None = None,
) -> dict:
    """
    Delete a file from the workspace.

    When dry_run=True, only validates the file exists and returns its content
    for frontend preview (all-red highlighting) — does NOT delete.
    When dry_run=False, backs up content then deletes the file from disk.
    """
    abs_path = Path(workspace_root) / file_path
    if not abs_path.exists():
        return {"success": False, "error": f"File not found: {abs_path}"}
    if not abs_path.is_file():
        return {"success": False, "error": f"Not a file: {abs_path}"}

    try:
        old_content = abs_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Could not read {abs_path}: {e}"}

    if dry_run:
        return {
            "success": True, "message": "delete validated (dry_run)",
            "file": str(abs_path), "deleted_content": old_content,
            "total_lines": len(old_content.splitlines()),
        }

    stack = _undo_stack if _undo_stack is not None else _get_default_undo_stack()
    stack.append((str(abs_path), old_content))
    try:
        abs_path.unlink()
        return {
            "success": True, "message": f"Deleted {abs_path}",
            "file": str(abs_path), "deleted_content": old_content,
            "total_lines": len(old_content.splitlines()),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "file": str(abs_path)}


# ── write_file ───────────────────────────────────────────────────────────

def write_file(
    file_path: str,
    content: str,
    workspace_root: str = ".",
    _undo_stack: list | None = None,
) -> dict:
    """
    Write (overwrite) a complete file to disk.

    Migrated from patcher.py:apply_patch_to_disk.  Saves the previous
    content on the undo stack so undo_last_change() can roll back.
    """
    abs_path = Path(workspace_root) / file_path
    try:
        old = abs_path.read_text(encoding="utf-8") if abs_path.exists() else ""
    except Exception:
        old = ""
    stack = _undo_stack if _undo_stack is not None else _get_default_undo_stack()
    stack.append((str(abs_path), old))
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        return {"success": True, "message": f"Written {abs_path}", "file": str(abs_path), "content": content}
    except Exception as e:
        return {"success": False, "error": str(e), "file": str(abs_path)}
