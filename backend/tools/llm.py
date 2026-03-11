from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from ..config import MAX_TOKENS, MAX_ROUNDS

load_dotenv()

# Placeholder values often committed by mistake — treat as "not set"
_INVALID_KEY_MARKERS = frozenset(
    {
        "",
        "none",
        "null",
        "undefined",
        "your-api-key-here",
        "sk-xxx",
        "sk-placeholder",
    }
)


def _normalize_key(val: str | None) -> str | None:
    if val is None:
        return None
    v = val.strip()
    if not v or v.lower() in _INVALID_KEY_MARKERS:
        return None
    return v


def _deepseek_key() -> str | None:
    return _normalize_key(os.getenv("DEEPSEEK_API_KEY"))


def _openai_key() -> str | None:
    return _normalize_key(os.getenv("OPENAI_API_KEY"))


def llm_configured() -> bool:
    """True if at least one provider has a usable API key."""
    return bool(_deepseek_key() or _openai_key())


def primary_llm_provider() -> str:
    """Which provider is used when both keys exist: DeepSeek wins."""
    if _deepseek_key():
        return "deepseek"
    if _openai_key():
        return "openai"
    return "none"


@lru_cache(maxsize=16)
def get_llm(agent: str = "default", thinking: bool = False) -> ChatOpenAI:
    """
    Return ChatOpenAI for the given logical agent name.
    """
    ds = _deepseek_key()
    if ds:
        kwargs = {
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
            "api_key": ds,
            "base_url": "https://api.deepseek.com/v1",
            "temperature": 0.1,
            "max_tokens": MAX_TOKENS,
            "request_timeout": 60,
            "max_retries": 1,
        }
        # Enable thinking if requested or if it's the main chat agent.
        # Explicitly disable it otherwise — DeepSeek v4-pro may return
        # reasoning_content by default, which breaks tool-use loops when the
        # next request doesn't pass it back.
        if thinking or agent == "chat":
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        return ChatOpenAI(**kwargs)
    oa = _openai_key()
    if oa:
        return ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            api_key=oa,
            temperature=0.1,
            max_tokens=MAX_TOKENS,
            request_timeout=60,
            max_retries=1,
        )
    raise ValueError(
        "No LLM API key: set DEEPSEEK_API_KEY (recommended) or OPENAI_API_KEY in .env"
    )


async def call_llm(agent: str, system: str, user: str) -> tuple[str, int]:
    """Call LLM and return (content, total_tokens)."""
    llm = get_llm(agent)
    response = await llm.ainvoke(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    usage = response.response_metadata.get("token_usage", {})
    tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
    return response.content, tokens


async def call_llm_stream(agent: str, system: str, user: str):
    """Yields (type, chunk) where type is 'reasoning' or 'content'."""
    llm = get_llm(agent, thinking=True)
    async for chunk in llm.astream([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]):
        if hasattr(chunk, 'additional_kwargs') and 'reasoning_content' in chunk.additional_kwargs:
            yield 'reasoning', chunk.additional_kwargs['reasoning_content']
        elif hasattr(chunk, 'content') and chunk.content:
            yield 'content', chunk.content
        elif 'reasoning_content' in chunk.response_metadata:
             yield 'reasoning', chunk.response_metadata['reasoning_content']


async def call_llm_stream_with_tools(
    agent: str,
    system: str,
    user: str,
    tools: list | None = None,
    tool_executor=None,
    max_rounds: int = 30,
):
    """Streaming LLM call with an agentic tool-use loop.

    Yields (type, data) tuples:
      'reasoning'   -> str chunk (DeepSeek thinking content)
      'content'     -> str chunk (normal response text)
      'tool_call'   -> {'name': str, 'input': dict}
      'tool_result' -> {'name': str, 'output': str}
    """
    from langchain_core.messages import ToolMessage

    messages: list = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    # DeepSeek: tools + thinking are mutually exclusive → 400 error
    llm = get_llm(agent, thinking=not tools)
    runner = llm.bind_tools(tools) if tools else llm

    for _ in range(max_rounds):
        accumulated = None
        async for chunk in runner.astream(messages):
            if hasattr(chunk, 'additional_kwargs'):
                rc = chunk.additional_kwargs.get('reasoning_content', '')
                if rc:
                    yield 'reasoning', rc
            if chunk.content:
                yield 'content', chunk.content
            accumulated = chunk if accumulated is None else accumulated + chunk

        if not accumulated or not getattr(accumulated, 'tool_calls', None):
            break  # no tool calls → done

        # DeepSeek: strip reasoning_content when thinking is disabled (tools + thinking
        # are mutually exclusive). Otherwise the next request fails with 400 because
        # reasoning_content appears in history but thinking mode is off.
        if hasattr(accumulated, 'additional_kwargs'):
            accumulated.additional_kwargs.pop('reasoning_content', None)

        messages.append(accumulated)
        for tc in accumulated.tool_calls:
            yield 'tool_call', {'name': tc['name'], 'input': tc['args']}
            if tool_executor:
                try:
                    result_str = str(await tool_executor(tc['name'], tc['args']))[:10000]
                except Exception as exc:
                    result_str = f"Error executing {tc['name']}: {exc}"
            else:
                result_str = "(no executor configured)"
            yield 'tool_result', {'name': tc['name'], 'output': result_str}
            messages.append(ToolMessage(content=result_str, tool_call_id=tc['id']))

