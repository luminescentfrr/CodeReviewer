from __future__ import annotations
from .base import BaseAgent

SYSTEM = """你是技术文档专家。评估文档质量并为缺失文档的函数自动生成 docstring。

检测：
- MISSING_DOCSTRING（MEDIUM）：公开函数/类完全没有文档
- INCOMPLETE_DOCSTRING（LOW）：缺少参数或返回值说明
- MISLEADING_COMMENT（HIGH）：注释与代码逻辑不符
- MISSING_TYPE_HINTS（LOW）：Python 函数缺少类型标注

严格返回 JSON：
{
  "issues": [
    {
      "type": "MISSING_DOCSTRING",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 12,
      "function": "函数名",
      "fix": "建议",
      "confidence": 0.99
    }
  ],
  "generated_docs": {
    "函数名": "完整 docstring 字符串"
  },
  "summary": "文档整体评估"
}"""

SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class DocumenterAgent(BaseAgent):
    name = "documenter"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        funcs = ast.get("functions", [])
        lines = code.splitlines()
        undocumented = []
        for f in funcs:
            check = f["start_line"]
            if check < len(lines) and not lines[check].strip().startswith(('"""', "'''")):
                undocumented.append(f["name"])
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 函数总数: {len(funcs)}
疑似缺少文档: {', '.join(undocumented[:15]) or '无'}
类: {', '.join(ast.get('classes', [])[:10]) or '无'}

===== 代码 =====
{code}
================{ctx_section}

评估文档完整性，并为缺少 docstring 的公开函数生成规范文档。"""

    def process_data(self, data: dict) -> dict:
        return {"generated_docs": data.get("generated_docs", {})}


documenter_agent = DocumenterAgent().run
