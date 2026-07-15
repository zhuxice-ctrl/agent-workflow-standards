from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any


REQUIRED_L2_CAPABILITIES = frozenset({
    "definitions",
    "references",
    "calls",
    "imports",
    "source_ranges",
    "unresolved_edges",
})

LANGUAGE_EXTENSIONS = {
    "python": {".py"},
    "typescript": {".ts", ".tsx", ".mts", ".cts"},
    "javascript": {".js", ".jsx", ".mjs", ".cjs"},
}


def normalize_graph_config(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = config or {}
    return {
        "include": sorted({str(item).replace("\\", "/").strip("/") for item in raw.get("include", []) if str(item).strip("/")}),
        "exclude": sorted({str(item).replace("\\", "/").strip("/") for item in raw.get("exclude", []) if str(item).strip("/")}),
        "languages": sorted({str(item).lower() for item in raw.get("languages", []) if str(item).strip()}),
    }


def load_graph_config(project: Path) -> dict[str, Any]:
    path = project.resolve() / ".codegraph" / "config.json"
    if not path.exists():
        return normalize_graph_config({})
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid codegraph config: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("invalid codegraph config: root must be an object")
    return normalize_graph_config(value)


def _path_matches(path: str, pattern: str) -> bool:
    return path == pattern or path.startswith(pattern + "/") or fnmatchcase(path, pattern)


def file_in_graph_scope(path: str, language: str, config: dict[str, Any]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    scoped = normalize_graph_config(config)
    if scoped["languages"] and language.lower() not in scoped["languages"]:
        return False
    if scoped["include"] and not any(_path_matches(normalized, pattern) for pattern in scoped["include"]):
        return False
    return not any(_path_matches(normalized, pattern) for pattern in scoped["exclude"])


def stable_symbol_id(language: str, module: str, qualified_name: str, kind: str) -> str:
    return f"{language}:{module}:{qualified_name}:{kind}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _canonical_records(records: list[dict[str, Any]], ignored: set[str] | None = None) -> list[dict[str, Any]]:
    ignored = ignored or set()
    normalized = [
        {key: value for key, value in record.items() if key not in ignored}
        for record in records
    ]
    return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def graph_revision(
    files: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    semantics: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    payload = {
        "files": sorted((item["path"], item["sha256"]) for item in files),
        "providers": _canonical_records(providers),
        "config": config or {},
        "semantics": {
            key: _canonical_records(value, {"mtime_ns"})
            for key, value in sorted((semantics or {}).items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def validate_provider_result(result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    provider = result.get("provider") or "unknown"
    capabilities = set(result.get("capabilities", []))
    missing = sorted(REQUIRED_L2_CAPABILITIES - capabilities)
    if missing:
        errors.append(f"{provider} missing L2 capabilities: {', '.join(missing)}")
    for key in ("files", "modules", "symbols", "references", "calls", "imports", "unresolved_edges", "diagnostics"):
        if not isinstance(result.get(key), list):
            errors.append(f"{provider} result.{key} must be an array")
    symbol_ids = {item.get("stable_id") for item in result.get("symbols", [])}
    if None in symbol_ids:
        errors.append(f"{provider} emitted a symbol without stable_id")
    if len(symbol_ids) != len(result.get("symbols", [])):
        errors.append(f"{provider} emitted duplicate stable_id values")
    for edge_name in ("references", "calls"):
        for edge in result.get(edge_name, []):
            target = edge.get("symbol_id") if edge_name == "references" else edge.get("callee_symbol_id")
            if target and target not in symbol_ids:
                errors.append(f"{provider} {edge_name} edge targets unknown symbol {target}")
    return sorted(set(errors))
