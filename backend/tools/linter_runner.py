"""
linter_runner.py — Multi-Language Linter Execution Tool

Runs static analysis tools (pylint, mypy, eslint, etc.) and parses their output.
Provides unified issue format across different linters.
"""

from __future__ import annotations

import subprocess
import json
import re
import logging
import tempfile
import os
import sys
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class LinterRunner:
    """Unified interface for running multiple linters."""
    
    SUPPORTED_LINTERS = {
        "python": ["ruff", "flake8", "pylint", "mypy"],
        "javascript": ["eslint"],
        "typescript": ["eslint", "tsc"],
    }
    
    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()
    
    def run_linter(
        self,
        code: str,
        language: str,
        linter_name: Optional[str] = None,
    ) -> Dict:
        """
        Run a linter on code and return structured results.
        
        Args:
            code: Source code to lint
            language: Programming language
            linter_name: Specific linter to use (auto-detect if None)
        
        Returns:
            Dict with {linter, issues: [{line, column, severity, message, rule}]}
        """
        if language not in self.SUPPORTED_LINTERS:
            return {"linter": "none", "issues": [], "error": f"Unsupported language: {language}"}
        
        candidates = [linter_name] if linter_name else self._available_linters(language)

        if not candidates:
            return {"linter": "none", "issues": [], "error": "No linter available"}
        
        # Write code to temp file
        ext_map = {"python": ".py", "javascript": ".js", "typescript": ".ts"}
        ext = ext_map.get(language, ".txt")

        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=ext,
                delete=False,
                dir=self.workspace,
                encoding="utf-8",
            ) as f:
                f.write(code)
                temp_file = f.name

            runner_errors = []
            for candidate in candidates:
                result = self._run_one_linter(temp_file, candidate)
                if not self._is_runner_failure(result):
                    if runner_errors:
                        result["fallbacks"] = runner_errors
                    return result
                runner_errors.append(f"{candidate}: {self._runner_error_message(result)}")
                if linter_name:
                    break

            return {
                "linter": "none",
                "issues": [],
                "error": "All linters failed: " + " | ".join(runner_errors),
            }

        finally:
            if temp_file:
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    logger.warning("Failed to clean temp file %s: %s", temp_file, e)
    
    def _available_linters(self, language: str) -> list[str]:
        """Check which linters are installed for a language."""
        available = []
        for linter in self.SUPPORTED_LINTERS.get(language, []):
            try:
                result = subprocess.run(
                    self._linter_command(linter, "--version"),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0:
                    available.append(linter)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return available

    def _detect_available_linter(self, language: str) -> Optional[str]:
        """Backward-compatible helper: return the first available linter."""
        available = self._available_linters(language)
        return available[0] if available else None

    def _linter_command(self, linter_name: str, *args: str) -> list[str]:
        """Build a command that keeps Python linters in the backend's environment."""
        if linter_name in {"ruff", "flake8", "pylint", "mypy"}:
            return [sys.executable, "-m", linter_name, *args]
        return [linter_name, *args]

    def _run_one_linter(self, file_path: str, linter_name: str) -> Dict:
        if linter_name == "pylint":
            return self._run_pylint(file_path)
        if linter_name == "mypy":
            return self._run_mypy(file_path)
        if linter_name == "flake8":
            return self._run_flake8(file_path)
        if linter_name == "ruff":
            return self._run_ruff(file_path)
        if linter_name == "eslint":
            return self._run_eslint(file_path)
        return {"linter": linter_name, "issues": [], "error": "Linter not implemented"}

    def _is_runner_failure(self, result: Dict) -> bool:
        if result.get("error") and not result.get("issues"):
            return True
        for issue in result.get("issues", []):
            if str(issue.get("severity", "")).upper() == "FATAL":
                return True
        return False

    def _runner_error_message(self, result: Dict) -> str:
        if result.get("error"):
            return str(result["error"])
        for issue in result.get("issues", []):
            if str(issue.get("severity", "")).upper() == "FATAL":
                return issue.get("message", "fatal linter error")
        return "runner failed"
    
    def _run_pylint(self, file_path: str) -> Dict:
        """Run pylint and parse JSON output."""
        try:
            result = subprocess.run(
                self._linter_command("pylint", file_path, "--output-format=json", "--score=no"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            
            # pylint returns non-zero on issues, but that's expected
            output = result.stdout
            
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                details = (result.stderr or result.stdout or "").strip()[:500]
                return {"linter": "pylint", "issues": [], "error": f"Failed to parse pylint output: {details}"}
            
            issues = []
            for item in data:
                issues.append({
                    "line": item.get("line", 0),
                    "column": item.get("column", 0),
                    "severity": item.get("type", "warning").upper(),
                    "message": item.get("message", ""),
                    "rule": item.get("message-id", ""),
                })
            
            return {"linter": "pylint", "issues": issues}
        
        except subprocess.TimeoutExpired:
            return {"linter": "pylint", "issues": [], "error": "Timeout"}
        except Exception as e:
            return {"linter": "pylint", "issues": [], "error": str(e)}
    
    def _run_mypy(self, file_path: str) -> Dict:
        """Run mypy and parse output."""
        try:
            result = subprocess.run(
                self._linter_command("mypy", file_path, "--no-error-summary"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            
            issues = []
            # mypy output format: file.py:line: error: message
            pattern = re.compile(r"^.+:(\d+):(?:\s*(\d+):)?\s*(error|warning|note):\s*(.+)$")
            
            for line in result.stdout.splitlines():
                match = pattern.match(line)
                if match:
                    issues.append({
                        "line": int(match.group(1)),
                        "column": int(match.group(2)) if match.group(2) else 0,
                        "severity": match.group(3).upper(),
                        "message": match.group(4),
                        "rule": "type-check",
                    })
            
            return {"linter": "mypy", "issues": issues}
        
        except subprocess.TimeoutExpired:
            return {"linter": "mypy", "issues": [], "error": "Timeout"}
        except Exception as e:
            return {"linter": "mypy", "issues": [], "error": str(e)}
    
    def _run_flake8(self, file_path: str) -> Dict:
        """Run flake8 and parse output."""
        try:
            result = subprocess.run(
                self._linter_command("flake8", file_path, "--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            
            issues = []
            # flake8 format: file.py:line:col: CODE message
            pattern = re.compile(r"^.+:(\d+):(\d+):\s*([A-Z]\d+)\s+(.+)$")
            
            for line in result.stdout.splitlines():
                match = pattern.match(line)
                if match:
                    code = match.group(3)
                    # Map flake8 codes to severity
                    severity = "ERROR" if code.startswith("E") else "WARNING"
                    
                    issues.append({
                        "line": int(match.group(1)),
                        "column": int(match.group(2)),
                        "severity": severity,
                        "message": match.group(4),
                        "rule": code,
                    })
            
            return {"linter": "flake8", "issues": issues}
        
        except subprocess.TimeoutExpired:
            return {"linter": "flake8", "issues": [], "error": "Timeout"}
        except Exception as e:
            return {"linter": "flake8", "issues": [], "error": str(e)}
    
    def _run_ruff(self, file_path: str) -> Dict:
        """Run ruff and parse JSON output."""
        try:
            result = subprocess.run(
                self._linter_command("ruff", "check", file_path, "--output-format=json"),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"linter": "ruff", "issues": [], "error": "Failed to parse ruff output"}
            
            issues = []
            for item in data:
                issues.append({
                    "line": item.get("location", {}).get("row", 0),
                    "column": item.get("location", {}).get("column", 0),
                    "severity": item.get("severity", "warning").upper(),
                    "message": item.get("message", ""),
                    "rule": item.get("code", ""),
                })
            
            return {"linter": "ruff", "issues": issues}
        
        except subprocess.TimeoutExpired:
            return {"linter": "ruff", "issues": [], "error": "Timeout"}
        except Exception as e:
            return {"linter": "ruff", "issues": [], "error": str(e)}
    
    def _run_eslint(self, file_path: str) -> Dict:
        """Run eslint and parse JSON output."""
        try:
            result = subprocess.run(
                ["eslint", file_path, "--format=json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"linter": "eslint", "issues": [], "error": "Failed to parse eslint output"}
            
            issues = []
            for file_result in data:
                for msg in file_result.get("messages", []):
                    severity_map = {1: "WARNING", 2: "ERROR"}
                    issues.append({
                        "line": msg.get("line", 0),
                        "column": msg.get("column", 0),
                        "severity": severity_map.get(msg.get("severity", 1), "WARNING"),
                        "message": msg.get("message", ""),
                        "rule": msg.get("ruleId", ""),
                    })
            
            return {"linter": "eslint", "issues": issues}
        
        except subprocess.TimeoutExpired:
            return {"linter": "eslint", "issues": [], "error": "Timeout"}
        except Exception as e:
            return {"linter": "eslint", "issues": [], "error": str(e)}


# ── LangChain Tool Factory ─────────────────────────────────────────────────

def make_linter_tool(code: str, language: str):
    """
    Return a @tool that runs a static linter on the current file.
    The LLM calls it with no arguments; code and language are captured in the closure.
    """
    from langchain_core.tools import tool

    @tool
    def run_static_analysis() -> str:
        """
        Run a static linter (pylint / flake8 / ruff / eslint) on the code under review.
        Call this first to get precise line numbers before performing deeper analysis.
        Returns structured linter output or a message if no linter is available.
        """
        runner = LinterRunner()
        result = runner.run_linter(code, language)
        if "error" in result and not result.get("issues"):
            return f"Linter unavailable: {result['error']}"
        if not result.get("issues"):
            return f"Linter ({result.get('linter', 'none')}): no issues found."
        lines = [
            f"[{i['severity']}] L{i['line']}: {i['message']} ({i['rule']})"
            for i in result["issues"][:20]
        ]
        return f"Linter ({result['linter']}) — {len(result['issues'])} issue(s):\n" + "\n".join(lines)

    return run_static_analysis
