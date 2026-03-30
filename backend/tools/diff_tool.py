"""
diff_tool.py — Unified Diff Generation and Application

Provides tools for generating and applying unified diffs (patch files).
Supports multi-file patches and conflict detection.
"""

from __future__ import annotations

import difflib
import re
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def generate_unified_diff(
    original: str,
    modified: str,
    filename: str = "file",
    n_context: int = 3,
) -> str:
    """
    Generate a unified diff between two code strings.
    
    Args:
        original: Original code
        modified: Modified code
        filename: Filename to show in diff header
        n_context: Number of context lines around changes
    
    Returns:
        Unified diff string (empty if no changes)
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        n=n_context,
    )
    
    return "".join(diff)


def apply_unified_diff(
    original: str,
    diff_text: str,
) -> Tuple[bool, str, Optional[str]]:
    """
    Apply a unified diff to original code.
    
    Args:
        original: Original code string
        diff_text: Unified diff text
    
    Returns:
        Tuple of (success, result_code, error_message)
        - If success: (True, modified_code, None)
        - If failed: (False, original_code, error_message)
    """
    try:
        # Parse diff hunks
        hunks = _parse_unified_diff(diff_text)
        if not hunks:
            return False, original, "No valid hunks found in diff"
        
        lines = original.splitlines()
        
        # Apply hunks in reverse order (bottom-up) to preserve line numbers
        for hunk in reversed(hunks):
            start_line = hunk["start_line"] - 1  # Convert to 0-indexed
            
            # Remove old lines
            for _ in range(hunk["remove_count"]):
                if start_line < len(lines):
                    lines.pop(start_line)
            
            # Insert new lines
            for new_line in reversed(hunk["new_lines"]):
                lines.insert(start_line, new_line)
        
        result = "\n".join(lines)
        return True, result, None
        
    except Exception as e:
        logger.error("Failed to apply diff: %s", e)
        return False, original, str(e)


def _parse_unified_diff(diff_text: str) -> List[Dict]:
    """
    Parse unified diff text into structured hunks.
    
    Returns:
        List of {start_line, remove_count, add_count, old_lines, new_lines}
    """
    hunks = []
    current_hunk = None
    
    for line in diff_text.splitlines():
        # Hunk header: @@ -start,count +start,count @@
        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            
            match = re.match(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@", line)
            if match:
                old_start = int(match.group(1))
                old_start = int(match.group(1))
                new_start = int(match.group(3))

                current_hunk = {
                    "start_line": old_start,
                    "remove_count": 0,
                    "add_count": 0,
                    "old_lines": [],
                    "new_lines": [],
                }

        elif current_hunk:
            if line.startswith("-") and not line.startswith("---"):
                current_hunk["old_lines"].append(line[1:])
                current_hunk["remove_count"] += 1
            elif line.startswith("+") and not line.startswith("+++"):
                current_hunk["new_lines"].append(line[1:])
                current_hunk["add_count"] += 1
            elif line.startswith(" "):
                # Context line — appears in both old and new
                pass
    
    if current_hunk:
        hunks.append(current_hunk)
    
    return hunks


def generate_multi_file_patch(
    file_changes: List[Dict[str, str]],
) -> str:
    """
    Generate a multi-file patch from a list of file changes.
    
    Args:
        file_changes: List of {filename, original, modified}
    
    Returns:
        Combined unified diff for all files
    """
    patches = []
    
    for change in file_changes:
        filename = change["filename"]
        original = change["original"]
        modified = change["modified"]
        
        diff = generate_unified_diff(original, modified, filename)
        if diff:
            patches.append(diff)
    
    return "\n".join(patches)


def detect_conflicts(
    original: str,
    patch1: str,
    patch2: str,
) -> List[Dict]:
    """
    Detect conflicts between two patches applied to the same original code.
    
    Args:
        original: Original code
        patch1: First patch (unified diff)
        patch2: Second patch (unified diff)
    
    Returns:
        List of conflict descriptions: [{line, description}]
    """
    conflicts = []
    
    try:
        hunks1 = _parse_unified_diff(patch1)
        hunks2 = _parse_unified_diff(patch2)
        
        # Check for overlapping line ranges
        for h1 in hunks1:
            h1_start = h1["start_line"]
            h1_end = h1_start + h1["remove_count"]
            
            for h2 in hunks2:
                h2_start = h2["start_line"]
                h2_end = h2_start + h2["remove_count"]
                
                # Check if ranges overlap
                if not (h1_end < h2_start or h2_end < h1_start):
                    conflicts.append({
                        "line": h1_start,
                        "description": f"Patches conflict at lines {h1_start}-{h1_end} and {h2_start}-{h2_end}",
                    })
    
    except Exception as e:
        logger.error("Conflict detection failed: %s", e)
    
    return conflicts


def preview_patch(
    original: str,
    diff_text: str,
    context_lines: int = 5,
) -> str:
    """
    Generate a human-readable preview of what a patch will change.
    
    Args:
        original: Original code
        diff_text: Unified diff
        context_lines: Lines of context to show
    
    Returns:
        Formatted preview text
    """
    success, modified, error = apply_unified_diff(original, diff_text)
    
    if not success:
        return f"❌ Patch cannot be applied: {error}"
    
    # Generate side-by-side comparison
    original_lines = original.splitlines()
    modified_lines = modified.splitlines()
    
    preview = ["=== Patch Preview ===\n"]
    
    # Find changed line ranges
    for i, (old, new) in enumerate(zip(original_lines, modified_lines)):
        if old != new:
            # Show context
            start = max(0, i - context_lines)
            end = min(len(original_lines), i + context_lines + 1)
            
            preview.append(f"\n--- Around line {i+1} ---")
            for j in range(start, end):
                if j < len(original_lines):
                    prefix = "- " if j == i else "  "
                    preview.append(f"{prefix}{original_lines[j]}")
                if j == i and j < len(modified_lines):
                    preview.append(f"+ {modified_lines[j]}")
    
    return "\n".join(preview)
