"""Daily LLM token budget tracker."""
from __future__ import annotations

import os
import threading
import time


class TokenBudget:
    def __init__(self, daily_limit: int = 1_000_000):
        self.daily_limit = daily_limit
        self.used: int = 0
        self.reset_time: float = time.time() + 86400
        self._lock = threading.Lock()

    def can_spend(self, estimated_tokens: int) -> bool:
        with self._lock:
            if time.time() > self.reset_time:
                self.used = 0
                self.reset_time = time.time() + 86400
            if self.used + estimated_tokens > self.daily_limit:
                return False
            self.used += estimated_tokens
            return True


_token_budget: TokenBudget | None = None


def get_token_budget() -> TokenBudget:
    global _token_budget
    if _token_budget is None:
        limit = int(os.getenv("DAILY_TOKEN_LIMIT", "1000000"))
        _token_budget = TokenBudget(limit)
    return _token_budget
