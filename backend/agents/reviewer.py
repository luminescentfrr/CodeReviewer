from __future__ import annotations
from .base import BaseAgent

SYSTEM = """你是资深代码审查工程师。分析代码的：
1. 逻辑正确性（边界条件、异常处理、潜在 bug）
2. 命名规范（是否清晰、符合语言惯例）
3. 可读性（函数长度、嵌套深度、魔法数字）
4. 注释质量（是否准确、是否缺失关键说明）

严格返回 JSON，不含其他文字：
{
  "issues": [
    {
      "type": "MISSING_ERROR_HANDLING",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 15,
      "function": "函数名（可选）",
      "evidence": "触发该问题的代码片段",
      "fix": "具体修复建议",
      "confidence": 0.95
    }
  ],
  "summary": "整体评估（1-2句话）"
}"""

# Dual-mode prompts: JSON for structured output, TOOL for tool-use streaming
SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class ReviewerAgent(BaseAgent):
    name = "reviewer"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        funcs = ast.get("functions", [])
        func_list = "\n".join(
            f"  {f['name']}() 第{f['start_line']}-{f['end_line']}行 复杂度={f['complexity']}"
            for f in funcs[:20]
        ) or "  （未检测到函数）"
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 行数: {ast.get('lines','?')} | 函数:\n{func_list}

===== 代码 =====
{code}
================{ctx_section}

请识别所有代码质量问题。"""


reviewer_agent = ReviewerAgent().run
