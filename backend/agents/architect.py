from __future__ import annotations
from .base import BaseAgent

SYSTEM = """你是软件架构设计专家。分析代码的架构质量：

1. **SOLID原则违反**（SOLID_VIOLATION / HIGH）：
   - S: 单一职责 — 类/函数做了多件不相关的事
   - O: 开闭原则 — 扩展需要修改已有代码（大量 if/elif 判断类型）
   - L: 里氏替换 — 子类不能替代父类使用
   - I: 接口隔离 — 实现了不需要的方法
   - D: 依赖反转 — 高层模块直接依赖低层具体实现

2. **循环依赖**（CIRCULAR_DEPENDENCY / HIGH）：
   - 模块 A 导入 B，B 又导入 A
   - 函数间相互调用形成环路

3. **过度耦合**（TIGHT_COUPLING / MEDIUM）：
   - 函数直接操作其他模块的内部状态
   - 硬编码的外部服务地址/配置
   - 缺少抽象层，直接依赖具体实现类

4. **分层违反**（LAYER_VIOLATION / MEDIUM）：
   - Controller/View 层包含业务逻辑
   - 工具函数中混入业务规则

5. **代码重复**（CODE_DUPLICATION / LOW）：
   - 相同/相似逻辑出现在多处
   - 可提取的公共模式未抽象

6. **设计模式建议**（PATTERN_SUGGESTION / INFO）

严格返回 JSON：
{
  "issues": [
    {
      "type": "SOLID_VIOLATION|CIRCULAR_DEPENDENCY|TIGHT_COUPLING|LAYER_VIOLATION|CODE_DUPLICATION|PATTERN_SUGGESTION",
      "severity": "HIGH|MEDIUM|LOW|INFO",
      "message": "问题描述",
      "line": 20,
      "function": "函数名或类名",
      "evidence": "相关代码片段",
      "fix": "重构建议",
      "principle": "违反的具体原则（如 SRP / OCP）",
      "confidence": 0.85
    }
  ],
  "architecture_assessment": "优秀|良好|一般|较差",
  "summary": "架构质量整体评估"
}"""

SYSTEM_JSON = SYSTEM
SYSTEM_TOOL = SYSTEM_JSON  # prompts.py appends tool instructions


class ArchitectAgent(BaseAgent):
    name = "architect"
    system_prompt = SYSTEM

    def build_user_prompt(self, state: dict) -> str:
        code = state["code"]
        lang = state["language"]
        ast = state.get("ast", {})
        funcs = ast.get("functions", [])
        classes = ast.get("classes", [])
        imports = ast.get("imports", [])
        func_info = "\n".join(
            f"  {f['name']}() 第{f['start_line']}-{f['end_line']}行 复杂度={f['complexity']}"
            for f in funcs[:25]
        ) or "  （未检测到函数）"
        class_info = ", ".join(classes[:15]) or "无"
        import_info = "\n".join(f"  {imp}" for imp in imports[:20]) or "  无"
        project_ctx = state.get("project_context", "")
        ctx_section = f"\n\n===== 项目上下文 =====\n{project_ctx}\n====================" if project_ctx else ""
        return f"""语言: {lang} | 行数: {ast.get('lines','?')} | 函数: {len(funcs)} | 类: {len(classes)}

函数列表:
{func_info}

类: {class_info}

导入:
{import_info}

===== 代码 =====
{code}
================{ctx_section}

重点分析：SOLID原则、耦合度、分层、代码重复、可扩展性。"""

    def process_data(self, data: dict) -> dict:
        return {"architecture_assessment": data.get("architecture_assessment", "未知")}


architect_agent = ArchitectAgent().run
