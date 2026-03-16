from __future__ import annotations
from .base import BaseAgent
from ..tools.llm import call_llm

SYSTEM = """你是测试质量专家。分析代码的测试质量和可测试性：

1. **缺失测试**（MISSING_TEST / HIGH）：
   - 关键业务逻辑函数没有对应的测试
   - 含有复杂条件分支但无分支覆盖测试
   - 涉及数据库/网络/文件操作但无 mock 测试

2. **覆盖不足**（INCOMPLETE_COVERAGE / MEDIUM）：
   - 只测了正常路径，缺少边界值测试（空值、极值、类型错误）
   - 异常路径未覆盖（try/catch 的 except 分支）
   - 缺少回归测试（已知 bug 的防护测试）

3. **测试坏味道**（BAD_TEST_PATTERN / MEDIUM）：
   - 测试依赖执行顺序或外部状态（非隔离）
   - Mock/Patch 使用不当（mock 了被测对象本身）
   - 断言过于宽泛（assert True / assert is not None）
   - 测试函数名不描述预期行为

4. **不稳定测试**（FLAKY_TEST / LOW）：
   - 依赖时间、随机数、网络等不确定因素
   - sleep / time.time() 作为断言条件

5. **可测试性问题**（LOW_TESTABILITY / INFO）：
   - 函数过长（>50行），难以单元测试
   - 硬编码依赖，缺少依赖注入
   - 全局状态修改

严格返回 JSON：
{
  "issues": [
    {
      "type": "MISSING_TEST|INCOMPLETE_COVERAGE|BAD_TEST_PATTERN|FLAKY_TEST|LOW_TESTABILITY",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 15,
      "function": "函数名",
      "evidence": "相关代码片段",
      "fix": "建议（含示例测试代码骨架）",
      "confidence": 0.90
    }
  ],
  "test_coverage_estimate": "无测试|部分覆盖|较完整",
  "summary": "测试质量整体评估"
}"""

SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class TesterAgent(BaseAgent):
    name = "tester"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        funcs = ast.get("functions", [])
        test_funcs = [f for f in funcs if f["name"].startswith(("test_", "Test"))]
        biz_funcs = [f for f in funcs if not f["name"].startswith(("test_", "Test", "_"))]
        func_info = "\n".join(
            f"  {f['name']}() 第{f['start_line']}-{f['end_line']}行 复杂度={f['complexity']}"
            for f in biz_funcs[:20]
        ) or "  （未检测到业务函数）"
        test_info = "\n".join(
            f"  {f['name']}() 第{f['start_line']}行"
            for f in test_funcs[:20]
        ) or "  （未检测到测试函数）"
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 总函数: {len(funcs)} | 业务函数: {len(biz_funcs)} | 测试函数: {len(test_funcs)}

业务函数:
{func_info}

测试函数:
{test_info}

===== 代码 =====
{code}
================{ctx_section}

请分析测试质量，识别缺失测试和测试坏味道。"""

    def process_data(self, data: dict) -> dict:
        return {"test_coverage_estimate": data.get("test_coverage_estimate", "未知")}


tester_agent = TesterAgent().run


async def generate_targeted_test(original_code: str, fixed_code: str, issue_desc: str) -> str:
    """Generates a targeted pytest-compatible test case."""
    prompt = f"""
    Objective: Create a targeted regression test for the following bug.

    Issue Description: {issue_desc}

    Original Buggy Code:
    {original_code}

    Fixed Code:
    {fixed_code}

    Requirements:
    1. Use `pytest` framework.
    2. Write a test function that would FAIL with the original code but PASS with the fixed code.
    3. Include edge cases related to this specific bug.
    4. Output ONLY the valid Python code for the test file. Do not include any explanation.
    """
    raw, _ = await call_llm("tester_gen", "你是自动化测试工程师，擅长编写回归测试。", prompt)
    if "```python" in raw:
        raw = raw.split("```python")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()
    return raw.strip()
