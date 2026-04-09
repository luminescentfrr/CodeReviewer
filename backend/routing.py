"""Agent routing logic — extracted from main.py."""
from __future__ import annotations

from dataclasses import dataclass

FULL_AGENT_ORDER = ["reviewer", "security", "optimizer", "documenter", "tester", "architect"]


@dataclass
class AgentRoute:
    keywords: set[str]
    agents: list[str]


AGENT_ROUTES = [
    AgentRoute(
        {"整个", "全量", "全项目", "整个项目", "整个工程", "整个仓库",
         "代码库", "项目", "工程", "仓库", "repo", "repository", "codebase",
         "all files", "whole project", "entire project", "entire codebase"},
        FULL_AGENT_ORDER,
    ),
    AgentRoute(
        {"全面", "完整", "全部", "所有", "帮我看看", "帮我分析",
         "代码审查", "code review", "review"},
        FULL_AGENT_ORDER,
    ),
    AgentRoute(
        {"安全", "漏洞", "注入", "sql", "xss", "csrf", "密钥", "密码",
         "token", "secret", "security", "vuln", "rce", "ssrf"},
        ["security"],
    ),
    AgentRoute(
        {"性能", "优化", "慢", "效率", "复杂度", "内存", "缓存",
         "performance", "optimize", "speed", "cpu"},
        ["optimizer"],
    ),
    AgentRoute(
        {"测试", "test", "覆盖率", "单元", "pytest", "断言", "mock", "coverage"},
        ["tester"],
    ),
    AgentRoute(
        {"文档", "注释", "docstring", "说明", "doc"},
        ["documenter"],
    ),
    AgentRoute(
        {"架构", "设计", "模块", "耦合", "依赖", "重构", "architecture", "分层", "职责"},
        ["architect"],
    ),
    AgentRoute(
        {"审查", "检查", "bug", "错误", "问题", "代码质量", "规范", "issue"},
        ["reviewer"],
    ),
]

FULL_SCOPE_MARKERS = AGENT_ROUTES[0].keywords
REVIEW_INTENT_MARKERS = {"审查", "检查", "分析", "review", "code review", "audit"}
ONLY_MARKERS = {"只看", "只检查", "只分析", "only"}


def route_agents(message: str, has_code: bool) -> list[str]:
    """Route a chat request to specialist agents."""
    msg = (message or "").lower()

    # 全局审查触发
    if has_code and any(k in msg for k in FULL_SCOPE_MARKERS):
        return FULL_AGENT_ORDER
    if any(k in msg for k in FULL_SCOPE_MARKERS) and any(k in msg for k in REVIEW_INTENT_MARKERS):
        return FULL_AGENT_ORDER

    selected: set[str] = set()
    for route in AGENT_ROUTES[2:]:  # skip the first two (full-scope routes)
        if any(k in msg for k in route.keywords):
            selected.update(route.agents)

    if selected - {"reviewer"} and any(k in msg for k in ONLY_MARKERS):
        selected.discard("reviewer")

    if not selected and has_code and len(msg.strip()) > 10:
        selected.update(["reviewer", "security"])

    return [aid for aid in FULL_AGENT_ORDER if aid in selected]
