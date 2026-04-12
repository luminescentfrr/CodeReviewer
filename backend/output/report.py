from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
try:
    REPORTS_DIR.mkdir(exist_ok=True)
except Exception:
    pass

SEVERITY_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}


def save_report(result: dict, code: str, language: str) -> Path:
    """
    Save review result to a Markdown file in reports/.
    Returns the file path.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = REPORTS_DIR / f"review_{timestamp}.md"
    filename.write_text(
        _build_markdown(result, code, language, timestamp),
        encoding="utf-8",
    )
    return filename


def _build_markdown(result: dict, code: str, language: str, timestamp: str) -> str:
    issues   = result.get("issues", [])
    overall  = result.get("overall_score", 0)
    elapsed  = result.get("elapsed_ms", 0)
    tokens   = result.get("total_tokens", 0)

    # Score badge
    badge = "🟢 优秀" if overall >= 80 else "🟡 合格" if overall >= 60 else "🔴 需改进"

    lines = [
        f"# 代码审查报告",
        f"",
        f"> 生成时间: {timestamp.replace('_', ' ')}  |  语言: {language}  |  耗时: {elapsed/1000:.1f}s  |  Tokens: {tokens}",
        f"",
        f"---",
        f"",
        f"## 综合评分 {badge}",
        f"",
        f"| 维度 | 得分 |",
        f"|------|------|",
        f"| 🏆 综合 | **{overall:.1f}** |",
        f"| 🔧 代码质量 | {result.get('quality_score', 0):.1f} |",
        f"| 🛡 安全性 | {result.get('security_score', 0):.1f} |",
        f"| ⚡ 性能 | {result.get('performance_score', 0):.1f} |",
        f"| 📝 文档 | {result.get('doc_score', 0):.1f} |",
        f"| 🧪 测试质量 | {result.get('test_score', 0):.1f} |",
        f"| 🏗 架构设计 | {result.get('architecture_score', 0):.1f} |",
        f"",
        f"---",
        f"",
    ]

    # Issues by severity
    by_sev: dict[str, list] = {"HIGH": [], "MEDIUM": [], "LOW": [], "INFO": []}
    for issue in issues:
        by_sev.setdefault(issue.get("severity", "INFO"), []).append(issue)

    lines.append("## 问题清单")
    lines.append("")

    total = len(issues)
    if total == 0:
        lines.append("✅ 未发现任何问题。")
    else:
        for sev in ["HIGH", "MEDIUM", "LOW", "INFO"]:
            group = by_sev.get(sev, [])
            if not group:
                continue
            icon = SEVERITY_ICON[sev]
            lines.append(f"### {icon} {sev} ({len(group)})")
            lines.append("")
            for issue in group:
                line_info = f" · 第 {issue['line']} 行" if issue.get("line") else ""
                func_info = f" · `{issue['function']}`" if issue.get("function") else ""
                lines.append(f"#### {issue['type']}{line_info}{func_info}")
                lines.append(f"> {issue['message']}")
                if issue.get("evidence"):
                    lines.append(f"")
                    lines.append(f"```")
                    lines.append(issue["evidence"])
                    lines.append(f"```")
                if issue.get("fix"):
                    lines.append(f"")
                    lines.append(f"**修复建议：** {issue['fix']}")
                if issue.get("cwe"):
                    lines.append(f"")
                    lines.append(f"_参考: [{issue['cwe']}](https://cwe.mitre.org/data/definitions/{issue['cwe'].replace('CWE-','')}.html)_")
                if issue.get("principle"):
                    lines.append(f"")
                    lines.append(f"_原则: {issue['principle']}_")
                conf = issue.get("confidence", 0)
                lines.append(f"")
                lines.append(f"置信度: {conf*100:.0f}%  ·  来源: {issue.get('agent','?')}")
                lines.append("")

    # Conflicts
    conflicts = result.get("conflicts", [])
    if conflicts:
        lines += ["---", "", "## 智能体冲突记录", ""]
        for c in conflicts:
            func_info = f"`{c['function']}`" if c.get("function") else "未知位置"
            lines.append(f"- **{func_info}**: {c['agent_a']} 认为「{c['description_a']}」，{c['agent_b']} 认为「{c['description_b']}」→ {c['resolution']}")
        lines.append("")

    # Full AI report
    final_report = result.get("final_report", "")
    if final_report:
        lines += ["---", "", "## 详细分析报告", "", final_report, ""]

    # Patches (if any)
    patches = result.get("patches", [])
    if patches:
        lines += ["---", "", "## 修复补丁", ""]
        for i, patch in enumerate(patches):
            lines.append(f"### 补丁 {i+1}: {patch.get('description', '修复')}")
            lines.append(f"")
            if patch.get("diff"):
                lines.append("```diff")
                lines.append(patch["diff"])
                lines.append("```")
            conf = patch.get("confidence", 0)
            lines.append(f"置信度: {conf*100:.0f}%")
            lines.append("")

    # Original code
    lines += [
        "---",
        "",
        "## 原始代码",
        "",
        f"```{language}",
        code,
        "```",
        "",
    ]

    return "\n".join(lines)


def list_reports() -> list[dict]:
    """Return all saved reports sorted by newest first."""
    files = sorted(REPORTS_DIR.glob("review_*.md"), reverse=True)
    result = []
    for f in files:
        # Parse timestamp from filename: review_20240101_120000.md
        m = re.match(r"review_(\d{8})_(\d{6})\.md", f.name)
        if m:
            date_str = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:]}"
        else:
            date_str = f.stat().st_mtime
        result.append({"filename": f.name, "path": str(f), "created_at": date_str, "size": f.stat().st_size})
    return result
