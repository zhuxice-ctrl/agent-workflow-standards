#!/usr/bin/env python3
"""Build a lightweight ADworkflo codegraph index.

V1 scope:
- files
- languages
- line counts
- simple symbols
- simple imports
- likely test files

This is intentionally a portable baseline, not a full language server.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
}

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    "coverage",
    ".adworkflow",
    ".codegraph",
}


def rel(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def iter_source_files(project: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        root_path = Path(root)
        for name in files:
            path = root_path / name
            if path.suffix.lower() in SOURCE_EXTENSIONS:
                yield path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def count_lines(text: str) -> int:
    return 0 if not text else text.count("\n") + 1


def is_test_file(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    name = path.name.lower()
    return (
        "tests" in parts
        or "__tests__" in parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def extract_python(path: Path, text: str) -> tuple[list[dict], list[str]]:
    symbols: list[dict] = []
    imports: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, imports

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
            })
        elif isinstance(node, ast.ClassDef):
            symbols.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
            })
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return symbols, sorted(set(imports))


TS_JS_PATTERNS = [
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE)),
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b", re.MULTILINE)),
    ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE)),
    ("function", re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][\w$]*\s*=>", re.MULTILINE)),
]

IMPORT_RE = re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]|^\s*import\s+['\"]([^'\"]+)['\"]", re.MULTILINE)
REQUIRE_RE = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_js_like(text: str) -> tuple[list[dict], list[str]]:
    symbols: list[dict] = []
    for sym_type, pattern in TS_JS_PATTERNS:
        for match in pattern.finditer(text):
            symbols.append({
                "type": sym_type,
                "name": match.group(1),
                "line": line_for_offset(text, match.start()),
                "end_line": line_for_offset(text, match.start()),
            })
    imports = []
    for match in IMPORT_RE.finditer(text):
        imports.append(match.group(1) or match.group(2))
    imports.extend(match.group(1) for match in REQUIRE_RE.finditer(text))
    return symbols, sorted(set(imports))


GO_PATTERNS = [
    ("function", re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z_]\w*)\s*\(", re.MULTILINE)),
    ("struct", re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct\b", re.MULTILINE)),
    ("interface", re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+interface\b", re.MULTILINE)),
]


def extract_regex_symbols(text: str, patterns: list[tuple[str, re.Pattern]]) -> list[dict]:
    symbols: list[dict] = []
    for sym_type, pattern in patterns:
        for match in pattern.finditer(text):
            symbols.append({
                "type": sym_type,
                "name": match.group(1),
                "line": line_for_offset(text, match.start()),
                "end_line": line_for_offset(text, match.start()),
            })
    return symbols


def extract_for_file(path: Path, language: str, text: str) -> tuple[list[dict], list[str]]:
    if language == "python":
        return extract_python(path, text)
    if language in {"javascript", "typescript"}:
        return extract_js_like(text)
    if language == "go":
        return extract_regex_symbols(text, GO_PATTERNS), []
    return [], []


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lightweight ADworkflo codegraph index.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--out", default=None, help="Output index path. Defaults to .codegraph/index.json.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SystemExit(f"Project path is not a directory: {project}")

    out = Path(args.out).resolve() if args.out else project / ".codegraph" / "index.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    files = []
    symbols = []
    imports = []
    tests = []

    for path in sorted(iter_source_files(project)):
        text = read_text(path)
        language = SOURCE_EXTENSIONS[path.suffix.lower()]
        file_rel = rel(project, path)
        loc = count_lines(text)
        file_record = {
            "path": file_rel,
            "language": language,
            "loc": loc,
            "is_test": is_test_file(path),
        }
        files.append(file_record)
        if file_record["is_test"]:
            tests.append(file_rel)

        file_symbols, file_imports = extract_for_file(path, language, text)
        for symbol in file_symbols:
            symbol["file"] = file_rel
            symbols.append(symbol)
        for imported in file_imports:
            imports.append({"file": file_rel, "imports": imported})

    index = {
        "schema": "ADworkflo.codegraph.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "summary": {
            "file_count": len(files),
            "source_line_count": sum(f["loc"] for f in files),
            "languages": sorted({f["language"] for f in files}),
            "symbol_count": len(symbols),
            "import_count": len(imports),
            "test_file_count": len(tests),
        },
        "files": files,
        "symbols": symbols,
        "imports": imports,
        "tests": tests,
    }
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote codegraph index: {out}")
    print(json.dumps(index["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
