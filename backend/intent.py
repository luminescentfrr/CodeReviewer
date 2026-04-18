"""LLM-based intent classification — replaces brittle keyword matching.

Uses a single lightweight non-streaming LLM call (~150 tokens in, ~5 out)
to classify user messages into one of four intents.
"""

from __future__ import annotations

from .tools.llm import call_llm

INTENT_SYSTEM = (
    "你是代码审查助手的意图分类器。将用户消息分为四类，只返回一个词:\n"
    "- review: 用户要求分析/审查/检查/安全审计/性能分析/测试评估/架构评审/文档检查\n"
    "- repair: 用户要求修改/修复/重构/替换/创建/删除代码(即使是间接的,如\"按建议改\")\n"
    "- plan_exec: 用户要求执行已有的计划或方案(关键词:执行/开始/动手/按计划/跑/apply/start/run)\n"
    "- chat: 一般性技术问题或对话,不涉及对当前代码的具体操作\n\n"
    "规则:\n"
    "- 如果用户提到已有的建议/计划并要求执行,归类为 plan_exec\n"
    "- 如果用户要求修改代码(即使说\"补测试\"\"加文档\"\"重构\"),归类为 repair\n"
    "- 只有纯粹的分析/审查/检查请求才归类为 review\n"
    "只返回 review, repair, plan_exec, chat 中的一个词。"
)


async def classify_intent(user_message: str) -> str:
    """Classify user message intent with a single non-streaming LLM call.

    Returns one of: 'review', 'repair', 'plan_exec', 'chat'.
    Falls back to 'chat' on any error or unrecognized response.
    """
    try:
        content, _ = await call_llm("classifier", INTENT_SYSTEM, user_message)
        label = content.strip().lower()
        # Accept partial matches (LLM sometimes appends punctuation or newlines)
        for valid in ("review", "repair", "plan_exec", "chat"):
            if valid in label:
                return valid
        return "chat"
    except Exception:
        return "chat"
