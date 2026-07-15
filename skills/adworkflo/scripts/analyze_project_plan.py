#!/usr/bin/env python3
"""Analyze first-layer product/architecture docs and produce architecture_manifest.

This script is meant for pre-development or early-development projects where
current LOC is not a reliable complexity signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DOC_NAMES = {
    "prd.md",
    "arch.md",
    "todo.md",
    "project.md",
    "产品需求.md",
    "需求.md",
    "架构.md",
    "任务.md",
    "项目.md",
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
    ".codegraph",
    ".adworkflow",
    ".codex",
}

SIGNALS: dict[str, dict[str, Any]] = {
    "frontend_backend": {
        "score": 2,
        "patterns": ["前端", "后端", "服务端", "客户端", "页面", "接口", "frontend", "backend", "client", "server", "api", "route"],
        "modules": ["frontend", "backend"],
    },
    "database": {
        "score": 2,
        "patterns": ["数据库", "数据表", "表结构", "sqlite", "mysql", "postgres", "postgresql", "mongodb", "redis", "db", "orm", "schema"],
        "modules": ["database"],
    },
    "auth_permissions": {
        "score": 2,
        "patterns": ["登录", "注册", "权限", "鉴权", "认证", "角色", "auth", "permission", "role", "rbac", "token", "session"],
        "modules": ["auth_permissions"],
        "risks": ["permission boundary"],
    },
    "agent_rag_tools": {
        "score": 3,
        "patterns": ["agent", "智能体", "rag", "tool calling", "function calling", "工具调用", "大模型", "llm", "向量", "embedding", "检索", "知识库"],
        "modules": ["agent_orchestrator", "rag_pipeline", "tool_runtime"],
        "agent_features": ["tool_calling", "rag"],
        "risks": ["hallucination", "tool misuse"],
    },
    "memory_state": {
        "score": 3,
        "patterns": ["长期记忆", "短期记忆", "记忆", "状态机", "状态", "workflow", "工作流", "编排", "orchestrator", "多轮", "上下文", "worker", "reviewer"],
        "modules": ["memory_system", "state_machine"],
        "agent_features": ["long_term_memory", "stateful_orchestration"],
        "risks": ["state drift", "memory pollution"],
    },
    "third_party_services": {
        "score": 1,
        "patterns": ["第三方", "外部服务", "webhook", "openai", "anthropic", "claude", "stripe", "飞书", "微信", "支付宝", "github", "s3", "oss", "sms", "email"],
        "modules": ["third_party_integrations"],
        "risks": ["external dependency failure"],
    },
    "high_risk_actions": {
        "score": 4,
        "patterns": ["支付", "交易", "下单", "删除", "发消息", "发送", "写入生产", "凭证", "密钥", "隐私", "资金", "订单", "不可逆", "审计", "高风险"],
        "modules": ["risk_control"],
        "risks": ["irreversible action", "safety boundary"],
    },
    "multi_platform": {
        "score": 3,
        "patterns": ["移动端", "小程序", "app", "android", "ios", "electron", "浏览器插件", "extension", "pwa", "desktop", "多端"],
        "modules": ["multi_platform_clients"],
    },
    "deployment_observability": {
        "score": 2,
        "patterns": ["部署", "监控", "日志", "告警", "trace", "metrics", "observability", "docker", "kubernetes", "ci", "cd", "回滚", "审计"],
        "modules": ["deployment", "observability"],
        "risks": ["runtime observability gap"],
    },
    "tests_verification": {
        "score": 1,
        "patterns": ["测试", "验收", "回归", "单元测试", "集成测试", "e2e", "pytest", "vitest", "playwright", "verification"],
        "modules": ["testing"],
    },
}

COUNT_HINTS = [
    ("module_count", ["模块", "module"], 5, 10, 2, 4),
    ("api_count", ["接口", "api", "route", "endpoint"], 10, 25, 2, 4),
    ("page_count", ["页面", "screen", "view", "page"], 5, 12, 1, 3),
    ("table_count", ["数据表", "table", "schema"], 5, 12, 2, 4),
]


def iter_doc_candidates(project: Path) -> list[Path]:
    result: list[Path] = []
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        root_path = Path(root)
        depth = len(root_path.relative_to(project).parts)
        if depth > 3:
            dirs[:] = []
            continue
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            if name.lower() in DEFAULT_DOC_NAMES:
                result.append(root_path / name)
    return sorted(set(result))


def read_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="ignore")


def normalize(text: str) -> str:
    return text.lower()


def find_patterns(text_lower: str, patterns: list[str]) -> list[str]:
    hits = []
    for pattern in patterns:
        normalized = pattern.lower()
        if re.search(r"[a-z0-9]", normalized):
            matched = re.search(
                rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])",
                text_lower,
            )
        else:
            matched = normalized in text_lower
        if matched:
            hits.append(pattern)
    return hits


def count_pattern(text_lower: str, pattern: str) -> int:
    normalized = pattern.lower()
    if re.search(r"[a-z0-9]", normalized):
        return len(re.findall(
            rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])",
            text_lower,
        ))
    return text_lower.count(normalized)


def infer_count_score(text_lower: str) -> tuple[int, dict[str, int]]:
    score = 0
    details: dict[str, int] = {}
    for key, patterns, medium_threshold, large_threshold, medium_score, large_score in COUNT_HINTS:
        count = 0
        for pattern in patterns:
            count += count_pattern(text_lower, pattern)
        details[key] = count
        if count >= large_threshold:
            score += large_score
        elif count >= medium_threshold:
            score += medium_score
    return score, details


def classify(score: int) -> tuple[str, str, str]:
    if score <= 5:
        return "small", "architecture-first-l0-rg-manual-context", "solo"
    if score <= 14:
        return "medium", "architecture-first-l1-symbol-import-test-index", "solo-with-risk-review"
    return "large", "architecture-first-l2-semantic-codegraph", "orchestrator-with-workers-and-reviewers"


def unique(items: list[str]) -> list[str]:
    return sorted(set(item for item in items if item))


def resolve_docs(project: Path, docs: list[Path] | None) -> list[Path]:
    candidates = iter_doc_candidates(project) if docs is None else docs
    return [p for p in candidates if p.exists() and p.is_file()]


def relative_doc_path(project: Path, doc: Path) -> str:
    try:
        return doc.relative_to(project).as_posix()
    except ValueError:
        return str(doc)


MODULE_SECTION_NAMES = {
    "module planning",
    "module plan",
    "modules",
    "模块规划",
    "模块计划",
    "模块拆分",
}


def extract_declared_modules(arch_text: str) -> list[str]:
    """Extract explicit modules from the ARCH module-planning section."""
    lines = arch_text.splitlines()
    in_section = False
    heading_level = 0
    modules: list[str] = []
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().lower()
            if title in MODULE_SECTION_NAMES:
                in_section = True
                heading_level = level
                continue
            if in_section and level <= heading_level:
                break
        if not in_section:
            continue

        candidate = ""
        bullet = re.match(r"^\s*[-*+]\s+(.+?)\s*$", line)
        if bullet:
            candidate = bullet.group(1)
        elif line.strip().startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and not all(set(cell) <= {"-", ":"} for cell in cells):
                if cells[0].lower() not in {"module", "模块"}:
                    candidate = cells[0]
        if candidate:
            candidate = re.split(r"\s*[：:|]\s*", candidate, maxsplit=1)[0]
            candidate = candidate.strip(" `*_")
            if candidate:
                modules.append(candidate)
    return unique(modules)


def build_architecture_manifest(project: Path, docs: list[Path] | None = None) -> dict[str, Any]:
    """Build architecture_manifest data from first-layer product docs."""
    doc_paths = resolve_docs(project, docs)
    combined_parts = []
    analysis_basis = []
    source_hashes: dict[str, str] = {}
    doc_texts: dict[str, str] = {}
    for doc in doc_paths:
        text = read_doc(doc)
        if not text.strip():
            continue
        rel = relative_doc_path(project, doc)
        analysis_basis.append({"path": rel, "chars": len(text)})
        source_hashes[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc_texts[rel.lower()] = text
        combined_parts.append(f"\n\n# FILE: {rel}\n{text}")

    combined = "\n".join(combined_parts)
    text_lower = normalize(combined)

    detected_signals: dict[str, Any] = {}
    score = 0
    suggested_modules: list[str] = []
    agent_features: list[str] = []
    risk_areas: list[str] = []

    for key, config in SIGNALS.items():
        hits = find_patterns(text_lower, config["patterns"])
        detected = bool(hits)
        detected_signals[key] = {
            "detected": detected,
            "hits": hits,
            "score": config["score"] if detected else 0,
        }
        if detected:
            score += config["score"]
            suggested_modules.extend(config.get("modules", []))
            agent_features.extend(config.get("agent_features", []))
            risk_areas.extend(config.get("risks", []))

    count_score, count_details = infer_count_score(text_lower)
    score += count_score
    detected_signals["count_hints"] = {
        "score": count_score,
        "details": count_details,
    }

    size, context_strategy, execution_mode = classify(score)
    arch_text = "\n".join(
        text for path, text in doc_texts.items()
        if Path(path).name in {"arch.md", "架构.md"}
    )
    planned_modules = extract_declared_modules(arch_text)

    data_stores = []
    for store in ["sqlite", "mysql", "postgres", "postgresql", "mongodb", "redis", "vector_db", "向量库"]:
        if store.lower() in text_lower:
            data_stores.append("vector_db" if store == "向量库" else store)

    recommended_artifacts = [
        "task_spec.json",
        "context_manifest.json",
        "worker_state.json",
        "verification_result.json",
    ]
    if size in {"medium", "large"} or risk_areas:
        recommended_artifacts.append("review_findings.json")
    if size == "large":
        recommended_artifacts.extend([
            "semantic_slice.json",
            "context_preflight.json",
            "context_expansion_request.json",
            "impact_report.json",
        ])
    if size == "large":
        recommended_artifacts.extend(["risk_register", "module_map", "verification_plan"])

    if analysis_basis:
        next_actions = [
            "Confirm or adjust project_size if the heuristic is wrong.",
            "Create the first task_spec from PRD/ARCH/TODO.",
            "Generate context_manifest from architecture_manifest before code exists.",
        ]
        if size == "small":
            next_actions.append("Use rg/file tree and manual context_manifest; skip heavy codegraph until code grows.")
        elif size == "medium":
            next_actions.append("After initial code appears, build L1 symbol/import/test index.")
        else:
            next_actions.append("Plan architecture-first module boundaries and add reviewer for high-risk modules.")
            next_actions.append("After modules exist, build codegraph incrementally for impact analysis.")
        classification_source = "product_docs"
    else:
        next_actions = [
            "Add PRD.md, ARCH.md, TODO.md, PROJECT.md, or pass explicit --docs paths.",
            "Until product docs exist, use source_scan_fallback from init_adworkflow.py.",
        ]
        classification_source = "product_docs_empty"

    return {
        "schema": "ADworkflo.architecture_manifest.v1",
        "configured": bool(analysis_basis),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_size": size,
        "classification_source": classification_source,
        "expected_complexity_score": score,
        "context_strategy": context_strategy,
        "execution_mode": execution_mode,
        "analysis_basis": analysis_basis,
        "source_hashes": source_hashes,
        "detected_signals": detected_signals,
        "planned_modules": planned_modules,
        "suggested_modules": unique(suggested_modules),
        "data_stores": unique(data_stores),
        "agent_features": unique(agent_features),
        "risk_areas": unique(risk_areas),
        "recommended_artifacts": unique(recommended_artifacts),
        "recommended_next_actions": next_actions,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_profile(project: Path, manifest: dict[str, Any]) -> bool:
    if not manifest.get("analysis_basis"):
        return False

    profile_path = project / ".adworkflow" / "ADWORKFLOW_PROFILE.json"
    profile: dict[str, Any] = {}
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    profile.update({
        "project_size": manifest["project_size"],
        "context_strategy": manifest["context_strategy"],
        "execution_mode": manifest["execution_mode"],
        "classification_source": manifest["classification_source"],
        "expected_complexity_score": manifest["expected_complexity_score"],
        "planned_modules": manifest["planned_modules"],
        "suggested_modules": manifest.get("suggested_modules", []),
        "risk_areas": manifest["risk_areas"],
        "agent_features": manifest["agent_features"],
    })
    write_json(profile_path, profile)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze PRD/ARCH/TODO docs for ADworkflo execution planning.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--docs", nargs="*", default=None, help="Explicit markdown docs to analyze.")
    parser.add_argument("--out", default=None, help="Output path. Defaults to .adworkflow/architecture_manifest.json.")
    parser.add_argument(
        "--update-profile",
        action="store_true",
        help="Also merge result into .adworkflow/ADWORKFLOW_PROFILE.json when product docs exist.",
    )
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SystemExit(f"Project path is not a directory: {project}")

    docs = [Path(p).resolve() for p in args.docs] if args.docs else None
    manifest = build_architecture_manifest(project, docs)

    out = Path(args.out).resolve() if args.out else project / ".adworkflow" / "architecture_manifest.json"
    write_json(out, manifest)

    profile_updated = False
    if args.update_profile:
        profile_updated = merge_profile(project, manifest)

    print(f"Wrote architecture manifest: {out}")
    print(json.dumps({
        "project_size": manifest["project_size"],
        "score": manifest["expected_complexity_score"],
        "classification_source": manifest["classification_source"],
        "context_strategy": manifest["context_strategy"],
        "execution_mode": manifest["execution_mode"],
        "docs_analyzed": [item["path"] for item in manifest["analysis_basis"]],
        "profile_updated": profile_updated,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
