from __future__ import annotations

import time
import logging

from ..tools.llm import call_llm
from ..tools.agent_json import parse_llm_json_object

logger = logging.getLogger(__name__)


class BaseAgent:
    """Template method for review agents.

    Subclasses override:
      - name: str
      - system_prompt: str
      - build_user_prompt(state) -> str
      - process_data(data) -> dict  (optional, for custom return fields)
    """

    name: str = ""
    system_prompt: str = ""

    def build_user_prompt(self, state: dict) -> str:
        raise NotImplementedError

    def process_data(self, data: dict) -> dict:
        """Override to add custom fields beyond issues + summary."""
        return {}

    async def run(self, state: dict) -> dict:
        start = time.time()
        try:
            raw, tokens = await call_llm(self.name, self.system_prompt,
                                         self.build_user_prompt(state))
            data = parse_llm_json_object(raw, self.name)
            for issue in data.get("issues", []):
                issue["agent"] = self.name
            extra = self.process_data(data)
            return {
                self.name: {
                    "issues": data.get("issues", []),
                    "summary": data.get("summary", ""),
                    "tokens": tokens,
                    "ms": int((time.time() - start) * 1000),
                    **extra,
                }
            }
        except Exception as e:
            logger.error("%s failed: %s", self.name, e)
            return {
                self.name: {
                    "issues": [],
                    "summary": f"分析失败: {e}",
                    "tokens": 0, "ms": 0,
                }
            }
