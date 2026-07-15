from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .model import load_graph_config, validate_provider_result


PROVIDER_ROOT = Path(__file__).resolve().parents[2] / "providers" / "typescript"


def capability_status() -> dict[str, Any]:
    analyzer = PROVIDER_ROOT / "analyze.mjs"
    typescript = PROVIDER_ROOT / "node_modules" / "typescript" / "package.json"
    if not analyzer.exists():
        return {"available": False, "reason": f"TypeScript analyzer missing: {analyzer}"}
    if not typescript.exists():
        command = f'npm install --prefix "{PROVIDER_ROOT}" --ignore-scripts'
        return {"available": False, "reason": f"TypeScript provider runtime is not installed. Run: {command}", "setup_command": command}
    try:
        package = json.loads(typescript.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"available": False, "reason": f"Invalid TypeScript provider runtime: {error}"}
    return {
        "available": True,
        "provider": "typescript-compiler-api",
        "version": package.get("version", "unknown"),
        "languages": ["typescript", "javascript"],
    }


def analyze_project(project: Path, config: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    config = load_graph_config(project) if config is None else config
    status = capability_status()
    if not status["available"]:
        return None, status
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp) / "typescript-provider.json"
        graph_config = Path(temp) / "graph-config.json"
        graph_config.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
        process = subprocess.run(
            ["node", str(PROVIDER_ROOT / "analyze.mjs"), "--project", str(project.resolve()), "--out", str(out),
             "--graph-config", str(graph_config)],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if process.returncode != 0:
            return None, {
                **status,
                "available": False,
                "reason": f"TypeScript provider failed: {process.stderr.strip() or process.stdout.strip()}",
            }
        result = json.loads(out.read_text(encoding="utf-8"))
    errors = validate_provider_result(result)
    if errors:
        return None, {**status, "available": False, "reason": "; ".join(errors)}
    return result, status
