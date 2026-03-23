"""
code_search.py — AST-based Code Search Tool + LangChain Tool Factories

Provides fast symbol search across a codebase without vector embeddings.
Supports:
  - Find definition of a function/class
  - Find all references to a symbol
  - Find similar function signatures
  - Grep-like text search with context
"""

from __future__ import annotations

import re
import logging
from typing import List, Dict, Optional

from .ast_parser import parse_code

logger = logging.getLogger(__name__)


def find_symbol_definition(
    symbol_name: str,
    files: list[dict] | None = None,
) -> dict | None:
    """
    Find the definition of a function or class across all files.

    Args:
        symbol_name: Name of the function/class to find
        files: List of {filename, code, language}

    Returns:
        Dict with {filename, line, code_snippet} or None if not found
    """
    if files is None:
        files = []
    for file in files:
        try:
            ast_data = parse_code(file["code"], file.get("language", "python"))
            
            # Check functions
            for func in ast_data.get("functions", []):
                if func["name"] == symbol_name:
                    return {
                        "filename": file["filename"],
                        "line": func.get("start_line", 0),
                        "type": "function",
                        "code": func.get("code", ""),
                    }
            
            # Check classes
            if symbol_name in ast_data.get("classes", []):
                # Find the class definition line
                lines = file["code"].splitlines()
                for i, line in enumerate(lines):
                    if re.match(rf"\s*class\s+{re.escape(symbol_name)}\b", line):
                        # Extract class body (up to 20 lines)
                        snippet = "\n".join(lines[i:i+20])
                        return {
                            "filename": file["filename"],
                            "line": i + 1,
                            "type": "class",
                            "code": snippet,
                        }
        except Exception as e:
            logger.warning("Search failed for %s: %s", file["filename"], e)
    
    return None


def find_symbol_references(
    symbol_name: str,
    files: List[Dict[str, str]],
    exclude_definition: bool = True,
) -> List[Dict]:
    """
    Find all references to a symbol (function calls, class instantiations).
    
    Args:
        symbol_name: Symbol to search for
        files: List of {filename, code, language}
        exclude_definition: Skip the file where symbol is defined
    
    Returns:
        List of {filename, line, context} dicts
    """
    references = []
    definition_file = None
    
    if exclude_definition:
        defn = find_symbol_definition(symbol_name, files)
        if defn:
            definition_file = defn["filename"]
    
    # Use word boundary regex to avoid partial matches
    pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
    
    for file in files:
        if exclude_definition and file["filename"] == definition_file:
            continue

        try:
            lines = file["code"].splitlines()
        except KeyError:
            continue
        for i, line in enumerate(lines):
            if pattern.search(line):
                # Include 1 line of context before and after
                context_start = max(0, i - 1)
                context_end = min(len(lines), i + 2)
                context = "\n".join(lines[context_start:context_end])
                
                references.append({
                    "filename": file["filename"],
                    "line": i + 1,
                    "context": context,
                })
    
    return references


def find_similar_functions(
    target_func_name: str,
    files: List[Dict[str, str]],
    similarity_threshold: float = 0.6,
) -> List[Dict]:
    """
    Find functions with similar signatures or names (fuzzy matching).
    
    Args:
        target_func_name: Function name to match against
        files: List of {filename, code, language}
        similarity_threshold: Minimum similarity score (0-1)
    
    Returns:
        List of {filename, function_name, signature, similarity} dicts
    """
    results = []
    target_lower = target_func_name.lower()
    
    for file in files:
        try:
            ast_data = parse_code(file["code"], file.get("language", "python"))
            
            for func in ast_data.get("functions", []):
                func_name = func["name"]
                func_lower = func_name.lower()
                
                # Calculate simple similarity score
                # 1. Exact match → 1.0
                # 2. Contains target → 0.8
                # 3. Levenshtein-like (common prefix/suffix) → 0.5-0.7
                if func_lower == target_lower:
                    score = 1.0
                elif target_lower in func_lower or func_lower in target_lower:
                    score = 0.8
                else:
                    # Common prefix length
                    common_prefix = 0
                    for a, b in zip(target_lower, func_lower):
                        if a == b:
                            common_prefix += 1
                        else:
                            break
                    score = common_prefix / max(len(target_lower), len(func_lower))
                
                if score >= similarity_threshold:
                    # Extract function signature (first line)
                    sig = func.get("code", "").split("\n")[0].strip()
                    results.append({
                        "filename": file["filename"],
                        "function_name": func_name,
                        "signature": sig,
                        "similarity": round(score, 2),
                        "line": func.get("start_line", 0),
                    })
        except Exception as e:
            logger.warning("Similarity search failed for %s: %s", file["filename"], e)
    
    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results


def grep_search(
    pattern: str,
    files: List[Dict[str, str]],
    context_lines: int = 2,
    case_sensitive: bool = False,
) -> List[Dict]:
    """
    Grep-like text search with context lines.
    
    Args:
        pattern: Regex pattern to search for
        files: List of {filename, code, language}
        context_lines: Number of lines before/after to include
        case_sensitive: Whether to match case
    
    Returns:
        List of {filename, line, match, context} dicts
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        logger.error("Invalid regex pattern: %s", e)
        return []
    
    results = []
    
    for file in files:
        lines = file["code"].splitlines()
        for i, line in enumerate(lines):
            if regex.search(line):
                # Extract context
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = "\n".join(lines[start:end])
                
                results.append({
                    "filename": file["filename"],
                    "line": i + 1,
                    "match": line.strip(),
                    "context": context,
                })

    return results


# ── LangChain Tool Factories ───────────────────────────────────────────────
# Each factory captures (code, language) in a closure and returns a @tool
# that the LLM can call with only domain-relevant arguments.

def make_grep_tool(code: str, language: str):
    """Return a @tool that greps the current file for a regex pattern."""
    from langchain_core.tools import tool

    @tool
    def grep_code(pattern: str, context_lines: int = 2) -> str:
        """
        Search the code under review for a regex pattern.
        Use to find hardcoded secrets, dangerous patterns, or specific constructs.
        Returns matching lines with surrounding context.
        """
        files = [{"filename": "current_file", "code": code, "language": language}]
        results = grep_search(pattern, files, context_lines=context_lines)
        if not results:
            return "No matches found."
        return "\n".join(
            f"L{r['line']}: {r['match']}"
            + ("\n  " + r["context"].replace("\n", " | ") if r.get("context") else "")
            for r in results[:20]
        )

    return grep_code


def make_references_tool(code: str, language: str):
    """Return a @tool that counts call sites for a named function."""
    from langchain_core.tools import tool

    @tool
    def find_function_references(function_name: str) -> str:
        """
        Find all call sites of a named function in the current code.
        Use to measure call frequency and identify hot paths worth optimising.
        """
        files = [{"filename": "current_file", "code": code, "language": language}]
        refs = find_symbol_references(function_name, files, exclude_definition=False)
        if not refs:
            return f"No call sites found for '{function_name}'."
        return (
            f"'{function_name}' referenced {len(refs)} time(s):\n"
            + "\n".join(
                f"  L{r['line']}: {r['context'].splitlines()[0][:100]}"
                for r in refs[:10]
            )
        )

    return find_function_references


def make_similarity_tool(code: str, language: str):
    """Return a @tool that finds functions with similar names (DRY detection)."""
    from langchain_core.tools import tool

    @tool
    def find_similar_code(function_name: str) -> str:
        """
        Find functions in the current code that have similar names to the given function.
        Use to detect potential code duplication (DRY violations).
        """
        files = [{"filename": "current_file", "code": code, "language": language}]
        similar = find_similar_functions(function_name, files, similarity_threshold=0.6)
        similar = [s for s in similar if s["function_name"] != function_name]
        if not similar:
            return f"No similar functions found for '{function_name}'."
        return "\n".join(
            f"  {s['function_name']}() similarity={s['similarity']} L{s['line']}: {s['signature'][:80]}"
            for s in similar[:5]
        )

    return find_similar_code
