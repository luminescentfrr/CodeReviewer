"""
repair.py — Multi-Round Conversational Code Repair Agent (v2)

LLM directly modifies code via tool calls (replace_code, insert_code).
No JSON intermediate format. Frontend visualizes tool results in real-time.

Mode:
  "memory" — tools validate changes (dry_run) but don't write disk; frontend applies
  "disk"   — tools write directly to disk (for auto-heal with git safety)
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

from ..tools.llm import call_llm_stream_with_tools

logger = logging.getLogger(__name__)

# Tools that modify files — require user approval in disk mode
DESTRUCTIVE_TOOLS = {"write_file", "replace_code", "insert_code"}
from ..config import REPAIR_MAX_ROUNDS

# ── Unified system prompt (no JSON output — tools ARE the output) ─────────

SYSTEM_REPAIR = """你是代码修复专家。你**直接调用工具修改代码**，不需要输出 JSON 或 diff 格式。

工具列表（按使用频率排序）：
- read_file(file_path, offset, limit) — 读取文件（带行号）。分页查看时用 offset/limit
- replace_code(file_path, old_string, new_string) — 精确替换。old_string 必须唯一匹配
  失败(0匹配) → 缩小 old_string 范围或从 read_file 输出中逐字复制
  失败(>1匹配) → 前后各加 3-5 行上下文使其唯一
- insert_code(file_path, after_line, code) — 在指定行后插入新代码。
  用于添加缺失的函数/类/导入。（after_line=0 表示插入到文件开头）
- run_linter(file_path, language) — 修改后立即验证。file_path 参数传入被修改的文件路径
- run_tests(test_path) — 运行测试确认无回归
- list_tests() — 发现相关测试文件
- undo_last_change() — 撤销最近一次修改（出错时使用）

工作流程（严格按顺序，每一步都要真正调用工具）：
1. read_file 读取目标文件（最多 2 次，用 offset/limit 避免重复读同一区域）
2. 对每个具体问题，选择正确的工具：
   - 修改已有代码行 → replace_code（old_string 从 read_file 输出中逐字复制）
   - 添加缺失的函数/类/导入 → insert_code
3. 每次修改后立即 run_linter(file_path) 验证
   - 有 HIGH/MEDIUM 错误 → 分析 → 修正 → 再 run_linter（最多 2 轮修正）
4. 相关测试 → list_tests → run_tests
   - 测试失败 → 分析 → 修正 → 再 run_tests

硬性规则（违反导致修复失败）：
- 第 1-2 轮：read_file 读取和分析代码
- 第 3-8 轮：replace_code/insert_code 逐一修复 + run_linter 验证
- 第 9 轮：必须输出 ALL_DONE（完成）或 CANNOT_FIX: <原因>（无法修复）
- 到达第 10 轮系统会强制终止，未修复项全部丢失
- 每个 replace_code/insert_code 只改一个问题，不要一次改多个
- old_string 必须精确（缩进/空白和 read_file 输出完全一致）
- 修改其他文件前必须先 read_file 那个文件
- 如果 replace_code 连续失败 3 次 → 跳过该问题，在最终总结中说明
- 不确定的修复不要强行做，标注 CANNOT_FIX

每个 issue 的行号和修复方向已在上方列出，精准定位，不要泛泛通读整个文件。"""


def _build_issues_text(issues: list[dict]) -> str:
    """Build compact issue descriptions with line numbers for the prompt."""
    parts = []
    for i, issue in enumerate(issues):
        parts.append(
            f"\n[{i}] {issue.get('type', 'UNKNOWN')} | "
            f"严重程度={issue.get('severity', 'MEDIUM')} | "
            f"行号={issue.get('line', '?')}\n"
            f"  问题: {issue.get('message', '')}\n"
        )
        func = issue.get("function", "")
        if func:
            parts.append(f"  函数: {func}\n")
        evidence = issue.get("evidence", "")
        if evidence:
            parts.append(f"  相关代码:\n{evidence}\n")
        fix = issue.get("fix", "")
        if fix:
            parts.append(f"  修复方向: {fix}\n")
    return "".join(parts)


def _batch_issues(issues: list[dict]) -> list[dict]:
    """
    Group by file, limit per file, prioritize fixable over missing-code issues.
    Returns a flat list of issues (ordered by priority within each file).
    """
    # Group by file
    groups: dict[str, list[dict]] = {}
    for issue in issues:
        file = issue.get("file", "(unknown)")
        groups.setdefault(file, []).append(issue)

    result = []
    for _file, file_issues in groups.items():
        # Prioritize: issues with evidence + line number first
        fixable = [i for i in file_issues if i.get("evidence") and i.get("line")]
        missing = [i for i in file_issues if not i.get("evidence")]
        other = [i for i in file_issues if i not in fixable and i not in missing]
        selected = (fixable[:3] + missing[:1] + other[:1])[:4]
        result.extend(selected)
    return result


# ── Main entry point ──────────────────────────────────────────────────────

async def repair_agent_stream(
    code: str,
    language: str,
    issues: list[dict],
    file_path: str,
    tools: list[dict],
    tool_executor,
    mode: str = "memory",
    extra_context: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Multi-round repair loop.  Yields SSE event dicts:
      {'event': 'thinking',   'text': '...'}
      {'event': 'content',    'text': '...'}
      {'event': 'tool_call',  'name': '...', 'input': {...}}
      {'event': 'tool_result','name': '...', 'output': '...', 'change': {...}}
      {'event': 'done',       'status': 'ok'|'partial', 'summary': '...', 'tokens': N, 'ms': N}
      {'event': 'error',      'message': '...'}

    mode: "memory" (dry_run, frontend applies) or "disk" (actual writes)
    """
    start = time.time()

    if not issues:
        yield {"event": "done", "status": "ok", "summary": "没有需要修复的问题",
               "tokens": 0, "ms": 0}
        return

    # Batch issues: per-file, max 4, fixable prioritized
    selected = _batch_issues(issues)
    issues_text = _build_issues_text(selected)

    # Embed issues directly into the system prompt so the agent sees them immediately
    system = SYSTEM_REPAIR + f"\n\n═══ 当前任务 ({len(selected)} 个问题) ═══\n{issues_text}"

    user = (
        f"语言: {language} | 目标文件: {file_path}\n\n"
        f"原始代码（共 {len(code.splitlines())} 行）:\n```\n{code}\n```"
    )
    if extra_context:
        user += f"\n\n[补充上下文]\n{extra_context}"

    # Round tracking
    tool_call_count = 0
    consecutive_failures = 0
    HARD_LIMIT = REPAIR_MAX_ROUNDS

    try:
        async for ptype, data in call_llm_stream_with_tools(
            "patcher", system, user,
            tools=tools,
            tool_executor=tool_executor,
            max_rounds=HARD_LIMIT,
        ):
            if ptype == "reasoning":
                yield {"event": "thinking", "text": data}
            elif ptype == "content":
                txt = data if isinstance(data, str) else str(data)
                # Check for done signals
                if "ALL_DONE" in txt:
                    yield {"event": "content", "text": txt}
                    elapsed = int((time.time() - start) * 1000)
                    yield {
                        "event": "done", "status": "ok",
                        "summary": f"修复完成 — {tool_call_count} 次工具调用",
                        "tokens": 0, "ms": elapsed,
                    }
                    return
                elif "CANNOT_FIX" in txt:
                    yield {"event": "content", "text": txt}
                    elapsed = int((time.time() - start) * 1000)
                    yield {
                        "event": "done", "status": "partial",
                        "summary": f"部分修复 — {tool_call_count} 次工具调用，部分问题无法自动修复",
                        "tokens": 0, "ms": elapsed,
                    }
                    return
                yield {"event": "content", "text": txt}
            elif ptype == "tool_call":
                tool_call_count += 1
                if mode == "disk" and data["name"] in DESTRUCTIVE_TOOLS:
                    yield {
                        "event": "approval_required",
                        "tool": data["name"],
                        "input": data["input"],
                        "message": f"LLM 将执行 {data['name']} 修改文件，是否允许？",
                    }
                yield {"event": "tool_call", "name": data["name"], "input": data["input"]}
            elif ptype == "tool_result":
                # Parse result to extract change details for frontend visualization
                try:
                    result_obj = json.loads(data["output"]) if isinstance(data["output"], str) else data["output"]
                except (json.JSONDecodeError, TypeError):
                    result_obj = {"raw": str(data["output"])}
                yield {
                    "event": "tool_result",
                    "name": data["name"],
                    "output": data["output"],
                    "success": result_obj.get("success", True),
                    "change": result_obj if result_obj.get("success") else None,
                }

                # Track failures for early abort
                if isinstance(result_obj, dict) and not result_obj.get("success"):
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        yield {
                            "event": "done", "status": "partial",
                            "summary": f"连续 {consecutive_failures} 次工具调用失败，修复中止",
                            "tokens": 0, "ms": int((time.time() - start) * 1000),
                        }
                        return
                else:
                    consecutive_failures = 0

    except Exception as exc:
        logger.exception("repair_agent_stream failed")
        yield {"event": "error", "message": str(exc)}
        return

    # If we reach here, the agent exhausted all rounds without saying ALL_DONE
    elapsed = int((time.time() - start) * 1000)
    yield {
        "event": "done",
        "status": "partial",
        "summary": f"Agent 达到 {HARD_LIMIT} 轮限制，共 {tool_call_count} 次工具调用。请检查编辑器中的修改。",
        "tokens": 0, "ms": elapsed,
    }
