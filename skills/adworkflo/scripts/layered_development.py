#!/usr/bin/env python3
"""Create the three-layer/four-question ADworkflo development contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LAYER_DEFAULTS = {
    "presentation": {
        "final_goal": "Deliver an observable, operable, accessible user experience.",
        "in_scope": ["pages", "interactions", "client state", "responsive and accessibility states"],
        "out_of_scope": ["server business rules", "storage implementation"],
        "non_completion": ["Static UI only", "Success state only", "Mock integration presented as production completion"],
        "read_first": ["PRD.md", "design specifications", "existing UI system", "consumer-facing protocol contracts"],
        "questions": ["Which user journeys and failure states must be observable?"],
        "evidence": ["interaction tests", "responsive/accessibility check", "end-to-end integration evidence"],
    },
    "protocol": {
        "final_goal": "Deliver stable business and service contracts with explicit behavior and failure semantics.",
        "in_scope": ["API contracts", "authorization", "validation", "business state transitions", "integration behavior"],
        "out_of_scope": ["visual presentation", "physical storage layout"],
        "non_completion": ["Route exists without contract tests", "Authorization or error semantics are unspecified", "Consumers cannot integrate deterministically"],
        "read_first": ["PRD.md", "ARCH.md", "callers and consumers", "external service contracts"],
        "questions": ["Which compatibility, idempotency, authorization and error guarantees are required?"],
        "evidence": ["contract tests", "authorization regression tests", "consumer integration evidence"],
    },
    "data": {
        "final_goal": "Deliver trustworthy, durable, consistent and evolvable data capabilities.",
        "in_scope": ["schemas", "queries", "indexes", "transactions", "migrations", "retention and recovery"],
        "out_of_scope": ["visual behavior", "transport presentation"],
        "non_completion": ["Schema without migration", "Missing integrity constraints", "No rollback, consistency or representative-volume verification"],
        "read_first": ["PRD.md", "ARCH.md", "existing schemas", "query paths", "migration history"],
        "questions": ["What integrity, retention, privacy, rollback and performance guarantees are required?"],
        "evidence": ["migration test", "integrity test", "rollback evidence", "representative query plan"],
    },
}


def new_layered_plan() -> dict:
    layers = []
    for layer_id, defaults in LAYER_DEFAULTS.items():
        layers.append({
            "layer_id": layer_id,
            "status": "planned",
            "not_applicable_reason": None,
            "final_goal": defaults["final_goal"],
            "scope": {
                "in_scope": defaults["in_scope"],
                "out_of_scope": defaults["out_of_scope"],
                "interfaces": [],
            },
            "non_completion_conditions": defaults["non_completion"],
            "exploration_and_audit": {
                "read_first": defaults["read_first"],
                "questions_to_resolve": defaults["questions"],
                "implementation_owner": None,
                "independent_auditor": None,
                "required_audit_evidence": defaults["evidence"],
            },
            "task_ids": [],
        })
    return {
        "schema": "ADworkflo.layer_plan.v1",
        "configured": True,
        "mode": "layered",
        "layers": layers,
        "capability_slices": [],
        "cross_layer_gates": [
            {"gate": gate, "status": "not_evaluated", "evidence": []}
            for gate in ("security", "privacy", "performance", "observability", "deployment", "end_to_end")
        ],
    }


def load_schema(repo_root: Path, name: str) -> dict:
    return json.loads((repo_root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = Path(args.project).resolve() / ".adworkflow" / "layer_plan.json"
    if output.exists() and not args.force:
        raise SystemExit(f"Layer plan already exists: {output}; use --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(new_layered_plan(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote layered development plan: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
