from __future__ import annotations
from .base import BaseAgent

SYSTEM = """你是代码安全专家。检测以下安全漏洞：

HIGH（立即修复）：SQL注入(CWE-89)、命令注入(CWE-78)、路径遍历(CWE-22)、硬编码密钥(CWE-798)
MEDIUM（建议修复）：XSS(CWE-79)、SSRF(CWE-918)、弱加密(CWE-327)、不安全随机数(CWE-330)、敏感日志(CWE-532)
LOW（注意）：缺少输入验证、不安全默认配置

严格返回 JSON：
{
  "issues": [
    {
      "type": "SQL_INJECTION",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 23,
      "function": "函数名（可选）",
      "evidence": "触发该问题的代码",
      "fix": "修复建议",
      "cwe": "CWE-89",
      "confidence": 0.97
    }
  ],
  "summary": "安全整体评估"
}"""

SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class SecurityAgent(BaseAgent):
    name = "security"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        imports = ", ".join(ast.get("imports", [])[:15]) or "无"
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 导入: {imports}

===== 代码 =====
{code}
================{ctx_section}

重点检查：用户输入处理、数据库操作、文件操作、网络请求。"""


security_agent = SecurityAgent().run
