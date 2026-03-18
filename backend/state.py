"""Type definitions for the review state dictionary."""
from __future__ import annotations

from typing import Any


class ReviewState(dict):
    """
    Typed wrapper over the review state dict.

    Keys used across the pipeline:
      code, language, ast, project_context,
      reviewer, security, optimizer, documenter, tester, architect,
      summarizer, issues, conflicts,
      quality_score, security_score, performance_score,
      doc_score, test_score, architecture_score, overall_score,
      final_report, total_tokens, start_time, errors
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
