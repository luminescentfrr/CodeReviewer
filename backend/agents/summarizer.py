from __future__ import annotations
import json, time, logging, os
from ..tools.llm import call_llm, call_llm_stream
from ..tools.agent_json import parse_llm_json_object

logger = logging.getLogger(__name__)

# Core analysis logic shared between modes
SYSTEM_CORE = """你是代码审查元裁判。负责：
1. **交叉验证**：检测专家间的矛盾并裁决。
2. **幻觉过滤**：确保建议有代码证据支持。
3. **去重合并**：整合重复的问题描述。
4. **六维评分**（0-100）：代码质量、安全、性能、文档、测试、架构。
"""

SYSTEM_JSON = SYSTEM_CORE + """
严格返回 JSON：
{
  "issues": [
    {
      "file": "文件路径（必填——每个 issue 必须标明属于哪个文件，方便后续修复定位）",
      "severity": "HIGH|MEDIUM|LOW",
      "agent": "reviewer|security|optimizer|documenter|tester|architect",
      "line": 行号,
      "message": "问题描述",
      "suggestion": "修复建议"
    }
  ],
  "conflicts": [...],
  "quality_score": 75.0,
  "security_score": 45.0,
  "performance_score": 80.0,
  "doc_score": 60.0,
  "test_score": 55.0,
  "architecture_score": 70.0,
  "overall_score": 64.25,
  "final_report": "# 代码审查报告\\n\\n..."
}"""

SYSTEM_CHAT = SYSTEM_CORE + """
你现在以「综合裁判 (Summarizer)」的身份直接与用户对话。
请参考各专家的分析结果，为用户提供一个专业的总结和建议。
要求：
- 直接输出 Markdown，不要包含 JSON。
- 语气专业且亲切。
- 必须包含各维度的评分概览。
- 如果用户有特定问题，请结合专家意见给出针对性回答。
- ⚠️ 重要：每个具体问题必须标注文件路径，格式为 **文件: xxx.py** 或 **xxx.py:行号**，方便后续修复定位。例如：
  - **engine.py:218** — np.mean() 在循环中重复计算...
  - **文件: models/vHeat_UNet.py** — Heat2D 中 8+ 次 .contiguous() 调用...
"""

async def summarizer_agent(state: dict) -> dict:
    start = time.time()
    agents_data = {k: state.get(k, {}) for k in ["reviewer", "security", "optimizer", "documenter", "tester", "architect"]}
    ast = state.get("ast", {})
    user = f"""代码信息: 语言={state['language']} | 各智能体结果:
{json.dumps(agents_data, ensure_ascii=False, indent=2)}

重要：每个 issue 必须保留各专家标注的 "file" 字段（文件路径），不要丢弃。
请生成最终审计 JSON。"""

    try:
        raw, tokens = await call_llm("summarizer", SYSTEM_JSON, user)
        data = parse_llm_json_object(raw, "summarizer")
        
        # Calculate total tokens from experts + summarizer
        total_tokens = sum(a.get("tokens", 0) for a in agents_data.values()) + tokens
        
        return {
            "issues":            data.get("issues", []),
            "conflicts":         data.get("conflicts", []),
            "quality_score":     data.get("quality_score", 0),
            "security_score":    data.get("security_score", 0),
            "performance_score": data.get("performance_score", 0),
            "doc_score":         data.get("doc_score", 0),
            "test_score":        data.get("test_score", 0),
            "architecture_score": data.get("architecture_score", 0),
            "overall_score":     data.get("overall_score", 0),
            "final_report":      data.get("final_report", ""),
            "total_tokens":      total_tokens,
            "ms":                int((time.time() - start) * 1000),
        }
    except Exception as e:
        logger.error("summarizer failed: %s", e)
        return {
            "overall_score": 0,
            "final_report": f"分析失败: {e}",
            "issues": [],
            "total_tokens": 0,
            "ms": 0,
        }

async def summarizer_agent_stream(state: dict, messages: list[dict] = None):
    """Streams the final summary response for chat mode."""
    agents_data = {k: state.get(k, {}) for k in ["reviewer", "security", "optimizer", "documenter", "tester", "architect"]}
    
    # Extract just the findings to save tokens in context
    context_str = json.dumps(agents_data, ensure_ascii=False)
    user_query = messages[-1]["content"] if messages else "请总结本次审查结果。"
    
    user = f"""[专家会诊记录]:
{context_str}

[用户问题]:
{user_query}

请作为综合裁判给出最终回答。"""

    async for ptype, chunk in call_llm_stream("summarizer", SYSTEM_CHAT, user):
        yield ptype, chunk
