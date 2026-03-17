from __future__ import annotations
import re
import logging

logger = logging.getLogger(__name__)


def parse_code(code: str, language: str) -> dict:
    """Parse source code, extract functions/classes/imports. Falls back to regex."""
    try:
        return _treesitter_parse(code, language)
    except Exception as e:
        logger.warning("Tree-sitter failed (%s), using regex fallback", e)
        return _regex_parse(code, language)


def _treesitter_parse(code: str, language: str) -> dict:
    from tree_sitter import Language, Parser

    if language == "python":
        import tree_sitter_python as tsl
    elif language in ("javascript", "typescript"):
        import tree_sitter_javascript as tsl
    else:
        return _regex_parse(code, language)

    parser = Parser(Language(tsl.language()))
    tree   = parser.parse(bytes(code, "utf-8"))
    lines  = code.splitlines()

    functions, classes, imports = [], [], []

    FUNC_TYPES = {
        "python":     ["function_definition"],
        "javascript": ["function_declaration", "arrow_function", "method_definition"],
    }

    def walk(node):
        if node.type in FUNC_TYPES.get(language, ["function_definition"]):
            name = next(
                (c.text.decode() for c in node.children if c.type == "identifier"),
                "<anonymous>",
            )
            start, end = node.start_point[0], node.end_point[0]
            func_code = "\n".join(lines[start : end + 1])
            functions.append({
                "name":       name,
                "start_line": start + 1,
                "end_line":   end + 1,
                "code":       func_code,
                "complexity": _complexity(func_code),
            })
        elif node.type in ("class_definition", "class_declaration"):
            name = next(
                (c.text.decode() for c in node.children if c.type == "identifier"), ""
            )
            if name:
                classes.append(name)
        elif node.type in ("import_statement", "import_from_statement"):
            imports.append(node.text.decode().splitlines()[0].strip())
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return {"functions": functions, "classes": classes, "imports": imports, "lines": len(lines)}


def _regex_parse(code: str, language: str) -> dict:
    lines = code.splitlines()
    functions, classes, imports = [], [], []

    for i, line in enumerate(lines):
        if m := re.match(r"\s*def\s+(\w+)\s*\(", line):
            functions.append({"name": m.group(1), "start_line": i+1, "end_line": i+1,
                               "code": line, "complexity": 1})
        elif m := re.match(r"\s*class\s+(\w+)", line):
            classes.append(m.group(1))
        elif re.match(r"\s*(import|from)\s+", line):
            imports.append(line.strip())

    return {"functions": functions, "classes": classes, "imports": imports, "lines": len(lines)}


def _complexity(code: str) -> int:
    keywords = ["if ", "elif ", "else:", "for ", "while ", "except ", "case "]
    return 1 + sum(code.count(k) for k in keywords)
