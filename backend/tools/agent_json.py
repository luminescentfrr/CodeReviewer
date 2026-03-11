from __future__ import annotations

import json
import logging

import json_repair

logger = logging.getLogger(__name__)


def strip_llm_json_fence(raw: str) -> str:
    """Remove optional ``` / ```json markdown fences from LLM output,
    even when narrative text precedes the fence."""
    import re
    text = raw.strip()
    # Find the first ``` fence anywhere in the text
    m = re.search(r"```(?:\w+)?\s*\n", text)
    if m:
        text = text[m.end():]  # Everything after the opening fence
    # Remove trailing ``` if present
    end = text.rfind("```")
    if end != -1:
        text = text[:end].rstrip()
    return text.strip()


def parse_llm_json_object(raw: str, log_label: str) -> dict:
    """Parse a JSON object from LLM text; fall back to json_repair on invalid JSON."""
    text = strip_llm_json_fence(raw)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(
            "%s: strict JSON failed (%s), retrying with json_repair",
            log_label,
            e,
        )
        data = json_repair.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{log_label} output is not a JSON object") from e
        return data
