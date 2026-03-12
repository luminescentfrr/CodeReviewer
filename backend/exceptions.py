"""Custom exceptions for CodeReview AI."""


class AgentError(Exception):
    """Agent execution failed."""

    def __init__(self, agent: str, message: str):
        self.agent = agent
        self.message = message
        super().__init__(f"[{agent}] {message}")


class ToolError(Exception):
    """Tool execution failed."""

    def __init__(self, tool: str, message: str):
        self.tool = tool
        self.message = message
        super().__init__(f"[{tool}] {message}")


class TokenBudgetExceeded(Exception):
    """Daily token budget has been exceeded."""

    def __init__(self, used: int, limit: int):
        self.used = used
        self.limit = limit
        super().__init__(f"Token budget exceeded: {used}/{limit}")
