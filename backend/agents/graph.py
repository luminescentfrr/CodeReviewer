from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator

from langgraph.graph import StateGraph, END

from .reviewer   import reviewer_agent
from .security   import security_agent
from .optimizer  import optimizer_agent
from .documenter import documenter_agent
from .tester     import tester_agent
from .architect  import architect_agent
from .summarizer import summarizer_agent
from ..tools.ast_parser import parse_code


# ── State ─────────────────────────────────────────────────────────────────

AGENT_NAMES = ["reviewer", "security", "optimizer", "documenter", "tester", "architect"]


def initial_state(code: str, language: str, project_context: str = "") -> dict:
    return {
        "code":     code,
        "language": language,
        "ast":      {},
        "project_context": project_context,
        "reviewer":   {},
        "security":   {},
        "optimizer":  {},
        "documenter": {},
        "tester":     {},
        "architect":  {},
        "issues": [], "conflicts": [],
        "quality_score": 0, "security_score": 0,
        "performance_score": 0, "doc_score": 0,
        "test_score": 0, "architecture_score": 0,
        "overall_score": 0,
        "final_report": "",
        "total_tokens": 0,
        "start_time": time.time(),
        "errors": [],
    }


# ── Nodes ──────────────────────────────────────────────────────────────────

async def preprocess_node(state: dict) -> dict:
    loop = asyncio.get_event_loop()
    ast  = await loop.run_in_executor(None, parse_code, state["code"], state["language"])
    return {"ast": ast}


async def parallel_agents_node(state: dict) -> dict:
    results = await asyncio.gather(
        reviewer_agent(state),
        security_agent(state),
        optimizer_agent(state),
        documenter_agent(state),
        tester_agent(state),
        architect_agent(state),
        return_exceptions=True,
    )
    merged: dict[str, Any] = {}
    errors = list(state.get("errors", []))

    for name, result in zip(AGENT_NAMES, results):
        if isinstance(result, Exception):
            errors.append(f"{name}: {result}")
            merged[name] = {"issues": [], "summary": str(result), "tokens": 0, "ms": 0}
        else:
            merged.update(result)

    merged["errors"] = errors
    return merged


# ── Graph ──────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(dict)
    g.add_node("preprocess",      preprocess_node)
    g.add_node("parallel_agents", parallel_agents_node)
    g.add_node("summarizer",      summarizer_agent)
    g.set_entry_point("preprocess")
    g.add_edge("preprocess",      "parallel_agents")
    g.add_edge("parallel_agents", "summarizer")
    g.add_edge("summarizer",      END)
    return g.compile()


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Streaming runner ───────────────────────────────────────────────────────

async def run_review_stream(
    code: str,
    language: str,
    project_context: str = "",
) -> AsyncGenerator[dict, None]:
    """Run the full review pipeline through LangGraph, yielding SSE progress events."""
    state = initial_state(code, language, project_context)
    graph = get_graph()

    async for event in graph.astream(state, stream_mode="updates"):
        for node_name, node_output in event.items():
            if node_name == "preprocess":
                yield {
                    "event": "progress", "agent": "preprocess",
                    "status": "done",
                    "detail": f"{len(node_output.get('ast', {}).get('functions', []))} 个函数",
                }
            elif node_name == "parallel_agents":
                for agent_name in AGENT_NAMES:
                    agent_data = node_output.get(agent_name, {})
                    if isinstance(agent_data, Exception):
                        yield {
                            "event": "progress", "agent": agent_name,
                            "status": "error", "detail": str(agent_data),
                        }
                    elif agent_data:
                        yield {
                            "event": "progress", "agent": agent_name,
                            "status": "done",
                            "detail": f"{len(agent_data.get('issues', []))} 个问题",
                            "ms": agent_data.get("ms", 0),
                        }
            elif node_name == "summarizer":
                yield {
                    "event": "progress", "agent": "summarizer",
                    "status": "done",
                    "detail": f"{len(node_output.get('issues', []))} 个问题汇总",
                }

    # LangGraph merges all node outputs into state; read the final values
    elapsed = int((time.time() - state["start_time"]) * 1000)
    yield {
        "event":             "completed",
        "issues":            state.get("issues", []),
        "conflicts":         state.get("conflicts", []),
        "quality_score":     state.get("quality_score", 0),
        "security_score":    state.get("security_score", 0),
        "performance_score": state.get("performance_score", 0),
        "doc_score":         state.get("doc_score", 0),
        "test_score":        state.get("test_score", 0),
        "architecture_score": state.get("architecture_score", 0),
        "overall_score":     state.get("overall_score", 0),
        "final_report":      state.get("final_report", ""),
        "total_tokens":      state.get("total_tokens", 0),
        "elapsed_ms":        elapsed,
        "agent_outputs": {
            name: state.get(name, {})
            for name in AGENT_NAMES
        },
    }
