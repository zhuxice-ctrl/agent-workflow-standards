# ADworkflo Review Checklist

Use review for medium/high risk tasks or when the change touches shared contracts.

## Review Inputs

- `.adworkflow/task_spec.json`
- `.adworkflow/context_manifest.json`
- patch or changed-file summary
- `.adworkflow/verification_result.json`

## Check

- Acceptance criteria are fully covered.
- Non-goals were respected.
- Tests or verification match the risk level.
- Public API, auth, permission, data, cache, state, and deployment risks are handled.
- No unrelated refactor, formatting churn, or hidden behavior change was introduced.
