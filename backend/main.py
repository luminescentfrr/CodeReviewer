from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import MAX_CODE_SIZE, MAX_FILES, REPORTS_DIR, HOST, PORT, RELOAD
from .routing import route_agents
from .tools.llm import llm_configured, primary_llm_provider
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel

from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.auth import AuthMiddleware
from .middleware.rate_limit import limiter
from slowapi.errors import RateLimitExceeded

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Stores the most recent review's structured output for repair context injection.
# Populated after summarizer completes in chat_stream / review_stream.
_last_review_state: dict | None = None

# Project root / frontend — used for SPA index (avoid mount "/" + StaticFiles, which often misses GET /).
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="CodeReview AI", docs_url="/api/docs")

# ── Middleware (order matters: outer → inner) ───────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "app://.",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(AuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda r, e:
    JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
)

# ── Request/Response schemas ───────────────────────────────────────────────

SUPPORTED_LANGUAGES = ["python", "javascript", "typescript", "java", "cpp", "go"]


class ReviewRequest(BaseModel):
    code:     str
    language: str = "python"


class FileItem(BaseModel):
    """A single file in a project review request."""
    filename: str
    code:     str
    language: str = "python"


class ProjectReviewRequest(BaseModel):
    """Multi-file project review request."""
    files:        list[FileItem]
    primary_file: str = ""     # Auto-detected if empty


class ChatRequest(BaseModel):
    messages: list[dict]
    files: list[FileItem] = []
    primary_file: str = ""
    workspace_root: str = ""


class PatchRequest(BaseModel):
    """Request to generate fix patches for selected issues."""
    code:      str
    language:  str = "python"
    issues:    list[dict]       # Selected issues to fix
    file_path: str = ""         # Actual file path in project (for tool resolution)


# ── API Routes ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status":           "ok",
        "llm_configured":   llm_configured(),
        "primary_provider": primary_llm_provider(),
    }


@app.post("/api/review/stream")
@limiter.limit("30/hour")
async def review_stream(req: ReviewRequest, request: Request):
    """
    SSE endpoint — streams per-agent progress then the final result.
    Each event is a JSON object on a `data:` line.
    """
    if not req.code.strip():
        raise HTTPException(400, "code is required")
    if req.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, f"unsupported language: {req.language}")
    if len(req.code) > MAX_CODE_SIZE:
        raise HTTPException(413, f"code too large (max {MAX_CODE_SIZE // 1000}KB)")
    if not llm_configured():
        raise HTTPException(
            500,
            "No LLM API key: set DEEPSEEK_API_KEY (recommended) or OPENAI_API_KEY in .env",
        )

    from .agents.graph import run_review_stream
    from .output.report import save_report

    async def event_generator():
        global _last_review_state
        result = None
        async for event in run_review_stream(req.code, req.language):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("event") == "completed":
                result = event

        # Save report to disk after streaming completes
        if result:
            # Store structured state for future repair context
            _last_review_state = {
                "issues": result.get("issues", []),
                "conflicts": result.get("conflicts", []),
                "overall_score": result.get("overall_score", 0),
                "final_report": result.get("final_report", ""),
            }
            try:
                path = await asyncio.to_thread(
                    save_report, result, req.code, req.language)
                yield f"data: {json.dumps({'event': 'saved', 'filename': path.name}, ensure_ascii=False)}\n\n"
                logger.info("Report saved: %s; stored %d issues", path.name, len(_last_review_state["issues"]))
            except Exception as e:
                logger.error("Failed to save report: %s", e)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/review/project")
@limiter.limit("30/hour")
async def review_project(req: ProjectReviewRequest, request: Request):
    """
    SSE endpoint — multi-file project review with 3-tier context.
    """
    if not req.files:
        raise HTTPException(400, "files list is required")
    if len(req.files) > MAX_FILES:
        raise HTTPException(413, f"too many files (max {MAX_FILES})")
    if not llm_configured():
        raise HTTPException(500, "No LLM API key configured")

    from .tools.context_analyzer import analyze_project
    from .agents.graph import run_review_stream
    from .output.report import save_report

    # Build project context
    files_data = [{"filename": f.filename, "code": f.code, "language": f.language}
                  for f in req.files]
    ctx = analyze_project(files_data, req.primary_file)
    primary = ctx["primary_file"]

    # Find primary file code
    primary_code = ""
    primary_lang = "python"
    for f in req.files:
        if f.filename == primary:
            primary_code = f.code
            primary_lang = f.language
            break

    if not primary_code:
        raise HTTPException(400, f"Primary file '{primary}' not found in files list")

    async def event_generator():
        global _last_review_state
        # Emit context analysis event
        detail_msg = f"{len(req.files)} 文件, 主文件: {primary}"
        yield f"data: {json.dumps({'event': 'progress', 'agent': 'context', 'status': 'done', 'detail': detail_msg}, ensure_ascii=False)}\n\n"

        result = None
        async for event in run_review_stream(
            primary_code, primary_lang,
            project_context=ctx["project_summary"],
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("event") == "completed":
                result = event

        if result:
            # Store structured state for future repair context
            _last_review_state = {
                "issues": result.get("issues", []),
                "conflicts": result.get("conflicts", []),
                "overall_score": result.get("overall_score", 0),
                "final_report": result.get("final_report", ""),
            }
            try:
                path = await asyncio.to_thread(
                    save_report, result, primary_code, primary_lang)
                yield f"data: {json.dumps({'event': 'saved', 'filename': path.name}, ensure_ascii=False)}\n\n"
                logger.info("Project report saved: %s; stored %d issues", path.name, len(_last_review_state["issues"]))
            except Exception as e:
                logger.error("Failed to save report: %s", e)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )




@app.post("/api/chat/stream")
@limiter.limit("30/hour")
async def chat_stream(req: ChatRequest, request: Request):
    if not llm_configured():
        raise HTTPException(500, "No LLM API key configured")

    from .tools.context_analyzer import analyze_project
    from .tools.llm import get_llm, call_llm_stream, call_llm_stream_with_tools
    from .agents.graph import preprocess_node
    import asyncio, json, os

    # 1. Prepare Context
    files_data = [{"filename": f.filename, "code": f.code, "language": f.language} for f in req.files]
    ctx = analyze_project(files_data, req.primary_file)
    
    primary_file = req.primary_file or ctx.get("primary_file", "")
    primary_code = ""
    primary_lang = "python"
    for f in req.files:
        if f.filename == primary_file:
            primary_code = f.code
            primary_lang = f.language
            break

    from .prompts import AGENT_PROMPTS, AGENT_TOOL_WHITELIST
    from .tools.tool_registry import build_default_registry
    registry = build_default_registry()
    registry.set_context(
        files_data=files_data,
        language=primary_lang,
        workspace_root=req.workspace_root or os.getcwd(),
    )

    user_message = req.messages[-1]["content"] if req.messages else ""

    # If no primary code yet (no file open), auto-pick the best file from files_data
    if not primary_code and files_data:
        primary_file = ctx.get("primary_file", "")
        for f in req.files:
            if f.filename == primary_file:
                primary_code = f.code
                primary_lang = f.language
                break

    # ── LLM-based intent classification (replaces brittle keyword matching) ──
    from .intent import classify_intent

    # Detect any plan in the conversation (for plan_exec intent validation)
    has_any_plan = False
    plan_text = ""
    for msg in req.messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if "计划" in content or "plan" in content.lower():
                has_any_plan = True
                plan_text = content  # last one wins

    intent = await classify_intent(user_message)
    is_plan_exec = has_any_plan and intent == "plan_exec"
    enter_repair = (intent in ("repair", "plan_exec") and is_plan_exec if intent == "plan_exec" else intent == "repair") and (primary_code or files_data)

    # Fix: simplify the enter_repair logic
    if intent == "repair":
        enter_repair = bool(primary_code or files_data)
        is_plan_exec = False
    elif intent == "plan_exec" and has_any_plan:
        enter_repair = bool(primary_code or files_data)
        is_plan_exec = True
    else:
        enter_repair = False
        is_plan_exec = False

    # Route agents only for review intent
    if intent == "review":
        selected_agents = route_agents(user_message, has_code=bool(primary_code)) or list(AGENT_PROMPTS.keys())
    else:
        selected_agents = []

    async def event_generator():
        global _last_review_state
        try:
            queue = asyncio.Queue()
            expert_findings = {}

            # Repair mode: explicit repair keywords OR executing an existing plan
            if enter_repair:
                from .prompts import SYSTEM_REPAIR_CHAT, REPAIR_TOOL_NAMES_CHAT

                repair_tools = registry.get_subset(REPAIR_TOOL_NAMES_CHAT)

                if is_plan_exec:
                    # ── Plan-Execution Mode ──
                    # Pass structured issues if available (zero-loss), fall back to plan text
                    plan_excerpt = plan_text[:8000]
                    if _last_review_state and _last_review_state.get("issues"):
                        issues_json = json.dumps(
                            _last_review_state["issues"], ensure_ascii=False, indent=2)
                        structured_block = (
                            f"\n\n[结构化任务列表 — {len(_last_review_state['issues'])} 个问题]\n"
                            f"```json\n{issues_json}\n```\n"
                        )
                    else:
                        structured_block = ""

                    repair_user = (
                        f"项目根目录: {req.workspace_root or os.getcwd()}\n"
                        f"当前打开文件: {primary_file or '(未指定)'}\n\n"
                        f"═══════════════════════════════════════\n"
                        f"以下是之前生成的修复计划，请严格按照计划执行：\n"
                        f"═══════════════════════════════════════\n\n"
                        f"{plan_excerpt}\n"
                        f"{structured_block}\n"
                        f"用户指令: {user_message}\n\n"
                        f"重要提醒:\n"
                        f"- 你上面看到的修复计划就是你要执行的任务列表\n"
                        f"- 按计划中的文件顺序逐一修复，不要跳过\n"
                        f"- 不要重新审查代码，直接按计划动手修改\n"
                        f"- 用 read_file 打开计划中列出的文件，定位到指定行号\n"
                        f"- 计划中每个问题就是一条任务，逐条完成"
                    )
                    system_prompt = SYSTEM_REPAIR_CHAT + (
                        "\n\n═══ 计划执行模式 ═══\n"
                        "你现在处于计划执行模式。用户消息中包含了一个已经制定好的修复计划。\n"
                        "你的任务不是重新审查代码，而是逐条执行计划中的修复项。\n"
                        "工作流程:\n"
                        "1. 从计划中提取第一条待修复的问题（文件名+行号+问题描述）\n"
                        "2. read_file 打开对应文件，定位到行号\n"
                        "3. replace_code 或 insert_code 精确修改\n"
                        "4. 完成后在回复中标记该条为 ✅已完成，然后继续下一条\n"
                        "5. 全部完成后告知用户\n\n"
                        "绝对不要做的事情:\n"
                        "- 不要重新审查整个项目的代码\n"
                        "- 不要修复计划之外的文件\n"
                        "- 不要输出新的审查结果，直接动手改代码"
                    )
                else:
                    # ── First-Repair Mode ──
                    # Build review context: prefer structured _last_review_state (zero loss),
                    # fall back to text extraction from message history.
                    review_context = ""
                    if _last_review_state and _last_review_state.get("issues"):
                        issues_json = json.dumps(
                            _last_review_state["issues"], ensure_ascii=False, indent=2)
                        review_context = (
                            f"\n\n[审查结果 — 结构化任务列表，共 {len(_last_review_state['issues'])} 个问题]\n"
                            f"```json\n{issues_json}\n```\n"
                            f"每个问题有 file(文件路径)、line(行号)、severity(严重度)、"
                            f"message(问题描述)、suggestion(修复建议)。\n"
                            f"先 read_file 确认行号，然后按列表逐项用 replace_code/insert_code 修复。\n"
                        )
                    else:
                        # Fallback: extract from message history
                        assistant_msgs = [m for m in req.messages if m.get("role") == "assistant"]
                        for i, msg in enumerate(assistant_msgs):
                            content = msg.get("content", "")
                            if i == len(assistant_msgs) - 1:
                                review_context += content[:6000]
                            else:
                                review_context += content[:2000]
                        if review_context:
                            review_context = f"\n\n[审查结果——据此规划修复]\n{review_context}\n"

                    repair_user = (
                        f"文件: {primary_file or '(未指定)'}\n"
                        f"语言: {primary_lang or 'python'}\n"
                        f"```\n{primary_code}\n```\n"
                        f"{review_context}\n"
                        f"用户请求: {user_message}"
                    )
                    system_prompt = SYSTEM_REPAIR_CHAT

                # Yield repair events directly (real-time, no buffering)
                full_output = ""
                async for ptype, data in call_llm_stream_with_tools(
                    "repair", system_prompt, repair_user,
                    tools=repair_tools,
                    tool_executor=registry.execute,
                    max_rounds=30,
                ):
                    if ptype == 'reasoning':
                        yield f"data: {json.dumps({'agent': 'repair', 'reasoning': data}, ensure_ascii=False)}\n\n"
                    elif ptype == 'content':
                        if len(full_output) < 100_000:
                            full_output += data
                        yield f"data: {json.dumps({'agent': 'repair', 'reasoning': data}, ensure_ascii=False)}\n\n"
                    elif ptype == 'tool_call':
                        yield f"data: {json.dumps({'agent': 'repair', 'tool_call': data}, ensure_ascii=False)}\n\n"
                    elif ptype == 'tool_result':
                        result_obj = None
                        try:
                            result_obj = json.loads(data['output']) if isinstance(data['output'], str) else data['output']
                        except (json.JSONDecodeError, TypeError):
                            result_obj = {"raw": str(data['output'])}
                        yield f"data: {json.dumps({'agent': 'repair', 'tool_result': {
                            'name': data['name'],
                            'output': data['output'],
                            'success': result_obj.get('success', True) if isinstance(result_obj, dict) else True,
                            'change': result_obj if isinstance(result_obj, dict) and result_obj.get('success') else None,
                        }}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps({'chunk': full_output}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'event': 'completed'}, ensure_ascii=False)}\n\n"
                return  # skip agent parallel + summarizer

            # (original review flow continues below)
            # Agents run whenever we have code OR project files to explore
            if primary_code or files_data:
                # 2.1 Preprocess (Show progress)
                agents_str = ", ".join(selected_agents)
                detected_primary = ctx.get("primary_file", primary_file)
                yield f"data: {json.dumps({'agent': 'preprocess', 'reasoning': f'路由到专家: {agents_str}', 'primary_file': detected_primary}, ensure_ascii=False)}\n\n"
                initial_state = {
                    "code": primary_code,
                    "language": primary_lang or "python",
                    "ast": {},
                    "project_context": ctx.get("project_summary", ""),
                    "files_data": files_data,
                }
                if primary_code:
                    pre_res = await preprocess_node(initial_state)
                    initial_state.update(pre_res)

                # Producer function for each agent
                async def agent_producer(aid):
                    try:
                        prompt_cfg = AGENT_PROMPTS[aid]
                        base_prompt = prompt_cfg["logic"](initial_state)
                        project_ctx = initial_state.get("project_context", "")
                        user_prompt = f"{base_prompt}\n\n[项目上下文]\n{project_ctx}" if project_ctx else base_prompt
                        full_output = ""
                        MAX_FULL_OUTPUT = 100_000
                        async for ptype, data in call_llm_stream_with_tools(
                            aid, prompt_cfg["system"], user_prompt,
                            tools=registry.get_subset(AGENT_TOOL_WHITELIST.get(aid, [])),
                            tool_executor=registry.execute,
                        ):
                            if ptype == 'content':
                                if len(full_output) < MAX_FULL_OUTPUT:
                                    full_output += data
                                await queue.put({"agent": aid, "reasoning": data})
                            elif ptype == 'reasoning':
                                await queue.put({"agent": aid, "reasoning": data})
                            elif ptype == 'tool_call':
                                await queue.put({"agent": aid, "tool_call": data})
                            elif ptype == 'tool_result':
                                await queue.put({"agent": aid, "tool_result": data})
                        expert_findings[aid] = full_output
                    except Exception as e:
                        logger.error(f"Agent {aid} failed: {e}")
                    finally:
                        await queue.put({"agent": aid, "done": True})

                # Start all agents in parallel
                tasks = [asyncio.create_task(agent_producer(aid)) for aid in selected_agents]
                
                # Consume from queue until all agents are done
                done_count = 0
                while done_count < len(tasks):
                    msg = await queue.get()
                    if "done" in msg:
                        done_count += 1
                    else:
                        yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

            # 3. Final Summarizer call (The unified "Moderator")
            from .agents.summarizer import summarizer_agent_stream
            
            # Inject expert findings into state for the summarizer
            initial_state.update(expert_findings)
            
            async for ptype, chunk in summarizer_agent_stream(initial_state, req.messages):
                if ptype == 'reasoning':
                    yield f"data: {json.dumps({'reasoning': chunk, 'agent': 'summarizer'}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            # Note: structured review state is captured from review_stream/review_project
            # endpoints (which use graph.py → summarizer_agent with proper dict state).
            # chat_stream uses summarizer_agent_stream which produces text, not JSON.

            yield f"data: {json.dumps({'event': 'completed'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error("Chat error: %s", e)
            yield f"data: {json.dumps({'chunk': f'\n\n❌ RuntimeError: {str(e)}'}, ensure_ascii=False)}\n\n"


    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


# ── Route modules ──────────────────────────────────────────────────────────
from .routes.reports import register as register_reports
register_reports(app)

# ── Serve frontend (single-page app) ───────────────────────────────────────

@app.get("/")
async def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(404, "frontend/index.html not found — check project layout")
    # HTMLResponse avoids rare Windows/sendfile edge cases with FileResponse for GET /.
    html = index_path.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Avoid noisy 404 on automatic browser request."""
    return Response(status_code=204)


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=RELOAD)
