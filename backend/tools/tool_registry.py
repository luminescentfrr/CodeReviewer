"""tool_registry.py — Unified LLM tool definitions and executor.

All OpenAI-format function-calling tool schemas and their Python implementations
are registered here.  Endpoints import `build_default_registry()` instead of
defining tools inline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = os.getenv("WORKSPACE_ROOT", os.getcwd())

REPAIR_TOOL_NAMES = [
    # Preview (non-destructive): read + lint + test only, no file modification
    "read_file",
    "run_linter",
    "run_tests",
    "list_tests",
    "generate_diff",
    "parse_ast",
]

REPAIR_TOOL_NAMES_HEAL = REPAIR_TOOL_NAMES + [
    # Heal (destructive): includes file modification tools
    "replace_code",
    "insert_code",
    "write_file",
    "undo_last_change",
]


@dataclass
class ToolDef:
    """One LLM-callable tool: OpenAI JSON schema + Python implementation."""

    name: str
    description: str
    parameters: dict  # JSON Schema properties dict
    fn: Callable[..., Any]
    required_params: list[str] = field(default_factory=list)

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required_params,
                },
            },
        }


class ToolRegistry:
    """Maps tool names → ToolDef; produces schemas; executes calls."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._context: dict[str, Any] = {}
        self._undo_stack: list[tuple[str, str]] = []

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [t.openai_schema() for t in self._tools.values()]

    def get_subset(self, names: list[str]) -> list[dict]:
        return [self._tools[n].openai_schema() for n in names if n in self._tools]

    def set_context(
        self,
        files_data: list[dict] | None = None,
        language: str | None = None,
        workspace_root: str | None = None,
    ) -> None:
        if files_data is not None:
            self._context["files_data"] = files_data
        if language is not None:
            self._context["language"] = language
        if workspace_root is not None:
            self._context["workspace_root"] = workspace_root

    def set_mode(self, mode: str) -> None:
        """'memory' = dry_run on write tools, changes reflected in editor only.
           'disk'   = write tools actually modify files on disk."""
        self._context["mode"] = mode

    async def execute(self, name: str, args: dict) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Inject context for tools that need files_data / language
        try:
            import inspect

            sig = inspect.signature(tool.fn)
            if "files" in sig.parameters and "files" not in args:
                fd = self._context.get("files_data")
                if fd:
                    args = {**args, "files": fd}
            if "language" in sig.parameters and "language" not in args:
                lang = self._context.get("language")
                if lang:
                    args = {**args, "language": lang}
            if "workspace_root" in sig.parameters and "workspace_root" not in args:
                wr = self._context.get("workspace_root")
                if wr:
                    args = {**args, "workspace_root": wr}
            # Memory mode → dry_run=True for destructive tools
            if "dry_run" in sig.parameters and "dry_run" not in args:
                if self._context.get("mode") == "memory":
                    args = {**args, "dry_run": True}
            # Inject per-registry undo stack for destructive tools
            if "_undo_stack" in sig.parameters and "_undo_stack" not in args:
                args = {**args, "_undo_stack": self._undo_stack}

            # Normalize parameter name aliases (LLMs vary between path / file_path).
            if "path" in sig.parameters and "path" not in args and "file_path" in args:
                args = {**args, "path": args.pop("file_path")}
            elif "file_path" in sig.parameters and "file_path" not in args and "path" in args:
                args = {**args, "file_path": args.pop("path")}

            # Filter args to only include parameters the function actually accepts
            valid_keys = set(sig.parameters.keys())
            args = {k: v for k, v in args.items() if k in valid_keys}

        except Exception as e:
            logger.warning("Parameter inspection for tool %s: %s", name, e)

        # Validate path arguments against workspace root
        ws = self._context.get("workspace_root", ".")
        for key in ("path", "file_path", "base_path"):
            if key in args and isinstance(args[key], str) and not os.path.isabs(args[key]):
                try:
                    from .file_tool import _validate_path as _vp
                    _vp(args[key], ws)
                except ValueError as e:
                    return json.dumps({"error": str(e)}, ensure_ascii=False)

        try:
            result = tool.fn(**args)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        if isinstance(result, dict) and "error" in result:
            return json.dumps(result, ensure_ascii=False)
        if result is None:
            return json.dumps({"result": "（未找到匹配项）"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False, default=str)


# ── Decorator-based registration ───────────────────────────────────────────

_tool_defs: dict[str, ToolDef] = {}

def register(name: str, description: str, parameters: dict,
             required_params: list[str] | None = None):
    """Decorator: register a function as an LLM-callable tool."""
    def decorator(fn):
        _tool_defs[name] = ToolDef(
            name=name, description=description,
            parameters=parameters, fn=fn,
            required_params=required_params or [],
        )
        return fn
    return decorator


# ── Factory ────────────────────────────────────────────────────────────────


def build_default_registry() -> ToolRegistry:
    from .ast_parser import parse_code as _parse_code
    from .code_search import find_symbol_definition as _find_def
    from .code_search import find_symbol_references as _find_refs
    from .diff_tool import generate_unified_diff as _gen_diff
    from .file_tool import glob_files as _glob
    from .file_tool import grep_files as _grep
    from .file_tool import read_file as _read
    from .file_tool import insert_code as _insert_code
    from .file_tool import replace_code as _replace_code
    from .file_tool import undo_last_change as _undo
    from .file_tool import write_file as _write_file
    from .file_tool import delete_file as _delete_file
    from .file_tool import _validate_path
    from .linter_runner import LinterRunner
    from .test_runner import TestRunner

    r = ToolRegistry()

    # ── 1. read_file ──
    r.register(
        ToolDef(
            name="read_file",
            description="读取项目中的任意文件，返回带行号的代码内容。支持分页（offset/limit）。用于查看依赖文件、导入的模块、测试文件等。",
            parameters={
                "path": {"type": "string", "description": "文件路径（相对于项目根目录的路径）"},
                "offset": {"type": "integer", "description": "起始行（0-indexed），默认 0"},
                "limit": {"type": "integer", "description": "最多返回行数，默认 2000"},
            },
            required_params=["path"],
            fn=lambda path, offset=0, limit=2000, workspace_root=".": _read(
                str(_validate_path(path, workspace_root)),
                offset=offset, limit=limit,
            ),
        )
    )

    # ── 2. grep_files ──
    r.register(
        ToolDef(
            name="grep_files",
            description="使用正则表达式搜索文件内容（类似 ripgrep）。返回匹配行及上下文。用于跨文件查找符号定义、危险模式、函数调用等。",
            parameters={
                "pattern": {"type": "string", "description": "正则表达式搜索模式"},
                "path": {"type": "string", "description": "搜索目标文件或目录（相对于项目根），默认 '.'"},
                "file_glob": {"type": "string", "description": "文件名过滤，如 '*.py'"},
                "context": {"type": "integer", "description": "匹配行前后的上下文行数，默认 2"},
            },
            required_params=["pattern"],
            fn=lambda pattern, path=".", file_glob="*", context=2, workspace_root=".": _grep(
                pattern,
                path=str(_validate_path(path, workspace_root)),
                file_glob=file_glob,
                context=context,
            ),
        )
    )

    # ── 3. glob_files ──
    r.register(
        ToolDef(
            name="glob_files",
            description="按 glob 模式查找文件，按修改时间排序（最新在前）。用于发现项目中的相关模块、配置文件、测试目录等。",
            parameters={
                "pattern": {"type": "string", "description": "Glob 模式，如 '**/*.py'、'src/**/*.ts'"},
                "base_path": {"type": "string", "description": "搜索根目录（相对于项目根），默认使用项目根目录"},
            },
            required_params=["pattern"],
            fn=lambda pattern, base_path=None, workspace_root=".": _glob(
                pattern,
                base_path=str(_validate_path(base_path or ".", workspace_root)),
            ),
        )
    )

    # ── 4. run_linter ──
    def _run_linter_wrapper(code=None, language="python", file_path=None, path=None, workspace_root="."):
        """Accept either code string or file_path; if file_path, read file first."""
        if code:
            return LinterRunner().run_linter(code, language)
        target = file_path or path
        if target:
            try:
                content = Path(workspace_root).resolve() / target
                return LinterRunner().run_linter(content.read_text(encoding="utf-8"), language)
            except Exception as e:
                return {"error": f"Could not read {target}: {e}"}
        return {"error": "code or file_path is required"}

    r.register(
        ToolDef(
            name="run_linter",
            description="对代码运行 linter（ruff/flake8/pylint/mypy/eslint），返回结构化的问题列表（含行号）。可以传入 code 字符串或 file_path 路径。",
            parameters={
                "code": {"type": "string", "description": "要检查的源代码（字符串）"},
                "language": {"type": "string", "description": "编程语言（python/javascript/typescript）"},
                "file_path": {"type": "string", "description": "要 lint 的文件路径（与 code 二选一）"},
            },
            required_params=["language"],
            fn=_run_linter_wrapper,
        )
    )

    # ── 5. find_symbol_definition ──
    r.register(
        ToolDef(
            name="find_symbol_definition",
            description="跨所有已提交文件查找某个函数或类的定义位置。返回文件名、行号和定义代码。用于理解模块间的调用关系。",
            parameters={
                "symbol_name": {"type": "string", "description": "要查找的函数名或类名"},
            },
            required_params=["symbol_name"],
            fn=_find_def,
        )
    )

    # ── 6. find_symbol_references ──
    r.register(
        ToolDef(
            name="find_symbol_references",
            description="查找某个符号在整个项目中的所有引用位置（调用点）。用于分析依赖链、影响范围和死代码。",
            parameters={
                "symbol_name": {"type": "string", "description": "要搜索的符号名"},
            },
            required_params=["symbol_name"],
            fn=_find_refs,
        )
    )

    # ── 7. generate_diff ──
    def _gen_diff_wrapper(original=None, modified=None, filename="file", old_code=None, new_code=None):
        """Wrapper that accepts common parameter name variations from LLMs."""
        orig = original or old_code or ""
        mod = modified or new_code or ""
        return _gen_diff(orig, mod, filename=filename or "file")

    r.register(
        ToolDef(
            name="generate_diff",
            description="生成两份代码之间的 unified diff。用于展示修复建议的具体变更。",
            parameters={
                "original": {"type": "string", "description": "原始代码（修改前）"},
                "modified": {"type": "string", "description": "修改后的代码"},
                "filename": {"type": "string", "description": "文件名（用于 diff 头部标识）"},
            },
            required_params=["original", "modified"],
            fn=_gen_diff_wrapper,
        )
    )

    # ── 8. parse_ast ──
    r.register(
        ToolDef(
            name="parse_ast",
            description="解析代码的 AST 结构，提取函数、类、导入和复杂度信息。用于快速了解文件结构。",
            parameters={
                "code": {"type": "string", "description": "要解析的源代码"},
                "language": {"type": "string", "description": "编程语言（python/javascript/typescript）"},
            },
            required_params=["code", "language"],
            fn=lambda code, language="python": _parse_code(code, language),
        )
    )

    # ── 9. replace_code ──
    r.register(
        ToolDef(
            name="replace_code",
            description="精确替换文件中的代码。old_string 必须在文件中唯一匹配。如果匹配失败(0次或>1次)则增加前后各3行上下文后重试。",
            parameters={
                "file_path": {"type": "string", "description": "要修改的文件路径（相对于项目根）"},
                "old_string": {"type": "string", "description": "要被替换的旧代码（必须唯一匹配）"},
                "new_string": {"type": "string", "description": "替换后的新代码"},
            },
            required_params=["file_path", "old_string", "new_string"],
            fn=lambda file_path, old_string, new_string, workspace_root=".", dry_run=False: _replace_code(
                file_path, old_string, new_string, workspace_root=workspace_root, dry_run=dry_run,
            ),
        )
    )

    # ── 10. insert_code ──
    r.register(
        ToolDef(
            name="insert_code",
            description="在指定行号之后插入新代码。用于添加缺失的函数、类、导入等无法通过 replace_code 匹配的代码。",
            parameters={
                "file_path": {"type": "string", "description": "要修改的文件路径（相对于项目根）"},
                "after_line": {"type": "integer", "description": "在此行号之后插入新代码（0=文件开头，N=第N行之后）"},
                "code": {"type": "string", "description": "要插入的新代码"},
            },
            required_params=["file_path", "after_line", "code"],
            fn=lambda file_path, after_line, code, workspace_root=".", dry_run=False: _insert_code(
                file_path, after_line, code, workspace_root=workspace_root, dry_run=dry_run,
            ),
        )
    )

    # ── 11. write_file ──
    def _write_file_wrapper(file_path=None, content=None, path=None, workspace_root="."):
        """Wrapper that accepts both 'file_path' and 'path' as the LLM varies in naming."""
        target = file_path or path
        if not target:
            return {"success": False, "error": "file_path or path is required"}
        return _write_file(target, content or "", workspace_root=workspace_root)

    r.register(
        ToolDef(
            name="write_file",
            description="将完整内容写入文件（覆盖）。用于在验证通过后将修复后的完整代码写入磁盘。调用时用 file_path 参数指定目标文件。",
            parameters={
                "file_path": {"type": "string", "description": "要写入的文件路径（相对于项目根）"},
                "content": {"type": "string", "description": "文件的完整新内容"},
            },
            required_params=["file_path", "content"],
            fn=_write_file_wrapper,
        )
    )

    # ── 12. delete_file ──
    def _delete_file_wrapper(file_path=None, path=None, workspace_root=".", dry_run=False):
        target = file_path or path
        if not target:
            return {"success": False, "error": "file_path or path is required"}
        return _delete_file(target, workspace_root=workspace_root, dry_run=dry_run)

    r.register(
        ToolDef(
            name="delete_file",
            description="删除项目中的文件。用于移除不再需要的代码文件。删除前会备份内容，可通过 undo_last_change 恢复。",
            parameters={
                "file_path": {"type": "string", "description": "要删除的文件路径（相对于项目根）"},
            },
            required_params=["file_path"],
            fn=_delete_file_wrapper,
        )
    )

    # ── 11. undo_last_change ──
    r.register(
        ToolDef(
            name="undo_last_change",
            description="撤销最近一次 replace_code 或 write_file 操作，恢复文件原始内容。",
            parameters={},
            required_params=[],
            fn=_undo,
        )
    )

    # ── 12. run_tests ──
    def _run_tests(test_path: str, workspace_root: str = ".") -> dict:
        runner = TestRunner(str(Path(workspace_root).resolve()))
        success, output = runner.run_pytest(test_path)
        return {"success": success, "output": output[:5000], "test_path": test_path}

    r.register(
        ToolDef(
            name="run_tests",
            description="运行 pytest 测试文件，返回测试结果。用于验证修复代码没有引入回归。",
            parameters={
                "test_path": {"type": "string", "description": "测试文件或目录路径"},
            },
            required_params=["test_path"],
            fn=_run_tests,
        )
    )

    # ── 13. list_tests ──
    def _list_tests(workspace_root: str = ".") -> dict:
        result = _glob("**/test*.py", base_path=workspace_root)
        files = [m["relative"] for m in result.get("matches", [])]
        return {"test_files": files, "total": len(files)}

    r.register(
        ToolDef(
            name="list_tests",
            description="列出项目中的所有测试文件（匹配 **/test*.py 模式）。用于发现可运行的测试。",
            parameters={},
            required_params=[],
            fn=_list_tests,
        )
    )

    # Also register tools declared via @register decorator
    for tool_def in _tool_defs.values():
        if tool_def.name not in r._tools:
            r.register(tool_def)

    return r
