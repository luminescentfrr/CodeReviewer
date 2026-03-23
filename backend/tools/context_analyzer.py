"""
context_analyzer.py — 3-Tier Project Context Analyzer

Builds a structured project context for multi-file code review:
  Layer 1 (50% tokens): Full code of the primary review file
  Layer 2 (30% tokens): Related file summaries + cross-referenced function code
  Layer 3 (10% tokens): Project metadata (file tree, dependency graph, tech stack)

Uses AST-based static analysis (no vector DB or embedding model required).
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path

from .ast_parser import parse_code
from ..config import MAX_CONTEXT_TOKENS, CHARS_PER_TOKEN as _CHARS_PER_TOKEN

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONTEXT_TOKENS = MAX_CONTEXT_TOKENS
CHARS_PER_TOKEN = _CHARS_PER_TOKEN


def analyze_project(
    files: list[dict],
    primary_file: str = "",
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> dict:
    """
    Build 3-tier project context for multi-file code review.

    Args:
        files: List of dicts with {filename, code, language}
        primary_file: Filename to focus on (auto-detected if empty)
        max_context_tokens: Maximum token budget for context

    Returns:
        dict with keys:
            primary_file: str — selected primary file name
            dependency_graph: dict — {filename: [imported_filenames]}
            file_summaries: dict — {filename: {functions, classes, imports, lines}}
            cross_references: list — [{name, code, from_file}] functions called by primary
            project_summary: str — structured text for agent prompt injection
            file_tree: str — visual file tree representation
            tech_stack: list — detected frameworks/libraries
    """
    if not files:
        return _empty_result()

    # Step 1: Parse AST for every file
    file_asts = {}
    file_codes = {}
    for f in files:
        filename = f["filename"]
        code = f["code"]
        language = f.get("language", "python")
        file_codes[filename] = code
        try:
            ast_data = parse_code(code, language)
            file_asts[filename] = ast_data
        except Exception as e:
            logger.warning("AST parse failed for %s: %s", filename, e)
            file_asts[filename] = {"functions": [], "classes": [], "imports": [], "lines": 0}

    # Step 2: Auto-detect primary file if not specified
    if not primary_file or primary_file not in file_codes:
        primary_file = _detect_primary_file(files, file_asts)

    # Step 3: Build dependency graph from import statements
    dep_graph = _build_dependency_graph(file_asts, set(file_codes.keys()))

    # Step 4: Build file summaries (Layer 2)
    file_summaries = {}
    for filename, ast_data in file_asts.items():
        file_summaries[filename] = _build_file_summary(filename, ast_data, file_codes[filename])

    # Step 5: Extract cross-references (functions called by primary from other files)
    cross_refs = _extract_cross_references(
        primary_file, file_codes, file_asts, dep_graph
    )

    # Step 6: Detect tech stack
    tech_stack = _detect_tech_stack(file_asts)

    # Step 7: Build file tree
    file_tree = _build_file_tree(list(file_codes.keys()))

    # Step 8: Generate structured project summary text
    project_summary = _generate_project_summary(
        primary_file=primary_file,
        file_summaries=file_summaries,
        dep_graph=dep_graph,
        cross_refs=cross_refs,
        file_tree=file_tree,
        tech_stack=tech_stack,
        max_tokens=max_context_tokens,
    )

    return {
        "primary_file": primary_file,
        "dependency_graph": dep_graph,
        "file_summaries": file_summaries,
        "cross_references": cross_refs,
        "project_summary": project_summary,
        "file_tree": file_tree,
        "tech_stack": tech_stack,
    }


def _empty_result() -> dict:
    return {
        "primary_file": "",
        "dependency_graph": {},
        "file_summaries": {},
        "cross_references": [],
        "project_summary": "",
        "file_tree": "",
        "tech_stack": [],
    }


def _detect_primary_file(files: list[dict], file_asts: dict) -> str:
    """
    Auto-detect the primary file to review.
    Heuristic priority:
      1. File with most functions (likely the main logic)
      2. Files named main.*, app.*, index.*, or containing 'if __name__'
      3. Largest file by line count
    """
    scores: dict[str, float] = {}
    for f in files:
        fn = f["filename"]
        ast = file_asts.get(fn, {})
        score = 0.0

        # Function count
        score += len(ast.get("functions", [])) * 2

        # Line count
        score += ast.get("lines", 0) * 0.1

        # Name heuristics
        basename = os.path.basename(fn).lower()
        if basename.startswith(("main", "app", "index", "server")):
            score += 20
        if "__main__" in f.get("code", ""):
            score += 15

        # Complexity bonus
        total_complexity = sum(
            func.get("complexity", 1) for func in ast.get("functions", [])
        )
        score += total_complexity * 0.5

        scores[fn] = score

    if not scores:
        return files[0]["filename"] if files else ""

    return max(scores, key=scores.get)


def _build_dependency_graph(file_asts: dict, known_files: set) -> dict:
    """
    Build file dependency graph from import statements.
    Maps each filename to a list of filenames it imports from.
    """
    # Build a lookup: module_name -> filename
    module_map: dict[str, str] = {}
    for fn in known_files:
        # "src/utils/helper.py" -> module names like "utils.helper", "helper"
        base = fn.replace("\\", "/")
        without_ext = os.path.splitext(base)[0]
        parts = without_ext.split("/")
        # Register multiple possible module paths
        for i in range(len(parts)):
            mod_name = ".".join(parts[i:])
            module_map[mod_name] = fn
        # Also register just the filename stem
        module_map[parts[-1]] = fn

    dep_graph: dict[str, list[str]] = {}

    for filename, ast_data in file_asts.items():
        deps = set()
        for imp in ast_data.get("imports", []):
            # Parse import statement to extract module name
            module_name = _parse_import_module(imp)
            if module_name:
                # Check if this module corresponds to a known file
                if module_name in module_map and module_map[module_name] != filename:
                    deps.add(module_map[module_name])
                # Try partial matching (e.g., "from utils import foo")
                parts = module_name.split(".")
                for i in range(len(parts)):
                    partial = ".".join(parts[:i+1])
                    if partial in module_map and module_map[partial] != filename:
                        deps.add(module_map[partial])

        dep_graph[filename] = sorted(deps)

    return dep_graph


def _parse_import_module(import_str: str) -> str:
    """Extract module name from an import statement string."""
    import_str = import_str.strip()

    # "from foo.bar import baz" -> "foo.bar"
    m = re.match(r"from\s+([\w.]+)\s+import", import_str)
    if m:
        return m.group(1)

    # "import foo.bar" -> "foo.bar"
    m = re.match(r"import\s+([\w.]+)", import_str)
    if m:
        return m.group(1)

    # JS/TS: "import { x } from './foo'" or "const x = require('./foo')"
    m = re.search(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", import_str)
    if m:
        path = m.group(1)
        # Remove relative prefix and extension
        path = re.sub(r"^[./]+", "", path)
        path = re.sub(r"\.(js|ts|jsx|tsx)$", "", path)
        return path.replace("/", ".")

    return ""


def _build_file_summary(filename: str, ast_data: dict, code: str) -> dict:
    """
    Build a concise summary of a single file for Layer 2 context.
    Includes function signatures, class names, imports, and docstrings.
    """
    functions = []
    for func in ast_data.get("functions", []):
        # Extract function signature (first line of the function)
        func_code = func.get("code", "")
        sig_line = func_code.split("\n")[0].strip() if func_code else func.get("name", "")
        functions.append({
            "name": func["name"],
            "signature": sig_line,
            "start_line": func.get("start_line", 0),
            "end_line": func.get("end_line", 0),
            "complexity": func.get("complexity", 1),
        })

    return {
        "functions": functions,
        "classes": ast_data.get("classes", []),
        "imports": ast_data.get("imports", []),
        "lines": ast_data.get("lines", 0),
    }


def _extract_cross_references(
    primary_file: str,
    file_codes: dict,
    file_asts: dict,
    dep_graph: dict,
) -> list[dict]:
    """
    Find functions in related files that are called by the primary file.
    Returns full code of those functions for deep context.
    """
    cross_refs = []
    primary_code = file_codes.get(primary_file, "")
    primary_deps = dep_graph.get(primary_file, [])

    if not primary_deps:
        return cross_refs

    # Collect all function names defined in dependency files
    for dep_file in primary_deps:
        dep_ast = file_asts.get(dep_file, {})
        for func in dep_ast.get("functions", []):
            func_name = func["name"]
            # Check if this function name appears in the primary file's code
            # Use word boundary to avoid partial matches
            if re.search(rf"\b{re.escape(func_name)}\b", primary_code):
                cross_refs.append({
                    "name": func_name,
                    "from_file": dep_file,
                    "code": func.get("code", ""),
                    "start_line": func.get("start_line", 0),
                })

    return cross_refs


def _detect_tech_stack(file_asts: dict) -> list[str]:
    """
    Detect frameworks and libraries from import statements across all files.
    """
    all_imports = set()
    for ast_data in file_asts.values():
        for imp in ast_data.get("imports", []):
            module = _parse_import_module(imp)
            if module:
                # Take the top-level module
                top = module.split(".")[0]
                all_imports.add(top)

    # Map known modules to framework names
    FRAMEWORK_MAP = {
        "fastapi": "FastAPI", "flask": "Flask", "django": "Django",
        "express": "Express.js", "react": "React", "vue": "Vue.js",
        "numpy": "NumPy", "pandas": "Pandas", "torch": "PyTorch",
        "tensorflow": "TensorFlow", "sqlalchemy": "SQLAlchemy",
        "pytest": "pytest", "unittest": "unittest",
        "requests": "Requests", "aiohttp": "aiohttp",
        "langchain": "LangChain", "langgraph": "LangGraph",
        "pydantic": "Pydantic", "celery": "Celery",
    }

    detected = []
    for mod in sorted(all_imports):
        if mod in FRAMEWORK_MAP:
            detected.append(FRAMEWORK_MAP[mod])

    return detected


def _build_file_tree(filenames: list[str]) -> str:
    """Build a visual file tree from a list of file paths."""
    if not filenames:
        return "(empty project)"

    # Sort and build tree structure
    sorted_files = sorted(filenames)
    lines = []
    for fn in sorted_files:
        # Indent by depth
        parts = fn.replace("\\", "/").split("/")
        indent = "  " * (len(parts) - 1)
        lines.append(f"{indent}📄 {parts[-1]}")

    return "\n".join(lines)


def _generate_project_summary(
    primary_file: str,
    file_summaries: dict,
    dep_graph: dict,
    cross_refs: list[dict],
    file_tree: str,
    tech_stack: list[str],
    max_tokens: int,
) -> str:
    """
    Generate structured project summary text for injection into agent prompts.
    Includes ALL project files so agents have full visibility into the codebase,
    not just the primary file's direct dependencies.

    Two-tier detail:
      Tier 1 (direct dependencies) — full summaries with function signatures
      Tier 2 (all other files)       — compact inventory with key symbols

    Respects token budget by truncating Tier 2 content first.
    """
    max_chars = int(max_tokens * CHARS_PER_TOKEN)
    primary_deps = set(dep_graph.get(primary_file, []))
    sections: list[tuple[int, str]] = []  # (priority, text) — lower priority is kept

    # ── Layer 3: Project metadata (priority 0 — always keep) ──
    meta = f"=== 项目上下文 ===\n"
    meta += f"文件数: {len(file_summaries)} | 主审查文件: {primary_file}\n"
    if tech_stack:
        meta += f"技术栈: {', '.join(tech_stack)}\n"
    meta += f"\n文件结构:\n{file_tree}\n"
    sections.append((0, meta))

    # Dependency info (priority 1)
    if primary_deps:
        dep_display = ', '.join(sorted(primary_deps))
        dep_text = f"\n依赖关系: {primary_file} 直接导入了 → {dep_display}\n"
        sections.append((1, dep_text))

    # ── Layer 2: Tier 1 — Direct dependency full summaries (priority 2) ──
    tier1_files: list[str] = []
    tier2_files: list[str] = []
    for filename in sorted(file_summaries.keys()):
        if filename == primary_file:
            continue
        if filename in primary_deps:
            tier1_files.append(filename)
        else:
            tier2_files.append(filename)

    for filename in tier1_files:
        summary = file_summaries[filename]
        parts = [f"\n--- {filename} (直接依赖 · 完整摘要) ---\n",
                 f"行数: {summary['lines']}\n"]
        if summary["classes"]:
            parts.append(f"类: {', '.join(summary['classes'])}\n")
        if summary["functions"]:
            parts.append("函数签名:\n")
            for func in summary["functions"]:
                parts.append(f"  {func['signature']}  (复杂度={func['complexity']})\n")
        sections.append((2, "".join(parts)))

    # ── Layer 2: Tier 2 — All other files (compact inventory, priority 3) ──
    if tier2_files:
        t2 = ["\n=== 项目其他文件（精简清单） ===\n",
              f"共 {len(tier2_files)} 个文件未直接被主文件导入，但都属于本项目，审查时需要关注:\n\n"]
        for filename in tier2_files:
            summary = file_summaries[filename]
            func_names = [f['name'] for f in summary.get('functions', [])]
            class_names = summary.get('classes', [])
            symbols = ', '.join(class_names + func_names[:6])
            if len(func_names) > 6:
                symbols += f" ...(+{len(func_names) - 6} 个函数)"
            line = f"  {filename} ({summary['lines']}行)"
            if symbols:
                line += f" — {symbols}"
            t2.append(line + "\n")
        t2.append("\n提示: 这些文件可能包含重要的业务逻辑、工具函数或配置。请使用 read_file 工具读取感兴趣的文件。\n")
        sections.append((3, "".join(t2)))

    # ── Cross-references (priority 4) ──
    if cross_refs:
        xref_text = "\n=== 跨文件引用（主文件调用的外部函数完整代码） ===\n"
        for ref in cross_refs[:10]:
            xref_text += f"\n# 来自 {ref['from_file']}:{ref['start_line']}\n"
            xref_text += ref["code"] + "\n"
        sections.append((4, xref_text))

    # Assemble in priority order, truncating lower-priority sections to fit budget
    sections.sort(key=lambda x: x[0])
    result = ""
    for _, text in sections:
        if len(result) + len(text) <= max_chars:
            result += text
        else:
            remaining = max_chars - len(result)
            if remaining > 200:
                result += text[:remaining]
                result += "\n\n... (上下文已裁剪以适应 token 限制) ..."
            break

    return result
