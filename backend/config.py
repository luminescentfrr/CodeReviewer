"""Centralized configuration for CodeReview AI."""
from __future__ import annotations

import os
from pathlib import Path

# ── Server ──
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))
RELOAD = os.getenv("RELOAD", "0") == "1"

# ── Limits ──
MAX_CODE_SIZE = 2_000_000        # bytes (2MB)
MAX_FILES = 200                  # per project review
MAX_FILE_SIZE_KB = 2_000         # workspace scan per-file limit (2MB)
MAX_SCAN_FILES = 500             # workspace scan file count cap

# ── LLM ──
MAX_ROUNDS = 30                  # tool-use loop
REPAIR_MAX_ROUNDS = 30           # repair agent round limit
MAX_TOKENS = 8192                # LLM output tokens (DeepSeek v4-pro: 16K max)
MAX_CONTEXT_TOKENS = 64000       # summarizer input context (DeepSeek: 128K total)
CHARS_PER_TOKEN = 3.5            # rough estimation for token counting
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "1000000"))

# ── SSE ──
SSE_HEARTBEAT_INTERVAL = 15      # seconds

# ── Paths ──
ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
REPORTS_DIR = ROOT_DIR / "reports"
