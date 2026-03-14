from __future__ import annotations
from .base import BaseAgent

SYSTEM = """你是性能优化专家。识别：
- O(n²)嵌套循环、N+1查询、不必要全量加载
- 内存问题：大列表一次加载、字符串拼接
- IO：同步阻塞、缺少批量操作、重复计算

严格返回 JSON：
{
  "issues": [
    {
      "type": "NESTED_LOOP_N2",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 34,
      "function": "函数名（可选）",
      "evidence": "触发代码",
      "fix": "修复建议",
      "confidence": 0.88
    }
  ],
  "summary": "性能整体评估"
}"""

SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class OptimizerAgent(BaseAgent):
    name = "optimizer"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        high_complexity = [f for f in ast.get("functions", []) if f.get("complexity", 0) >= 5]
        hc_list = "\n".join(
            f"  {f['name']}() 复杂度={f['complexity']} 第{f['start_line']}行"
            for f in high_complexity[:10]
        ) or "  无"
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 高复杂度函数:
{hc_list}

===== 代码 =====
{code}
================{ctx_section}

重点分析循环效率、内存使用、IO操作。"""


optimizer_agent = OptimizerAgent().run
