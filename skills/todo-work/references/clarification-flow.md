# TODOwork Clarification Flow

This flow prevents subagents from drifting when ARCH/TODO details are incomplete.

## Worker Behavior

When detail is missing:

1. Stop expanding beyond the current task.
2. Report the missing detail to the main window.
3. Wait for a main-window decision.
4. Continue only after receiving either a document-based decision or timeout fallback.
5. Record the event in `worker_state`.

## Main Window Behavior

1. Review PRD/ARCH/TODO.
2. If the answer is present, reply to the worker with the document-backed instruction.
3. If the answer is not present, ask the user.
4. If the configured timeout expires, choose the closest interpretation from PRD/ARCH/TODO.
5. Tell the worker the fallback instruction and require worker_state留痕.

## Worker State Fields

Use:

```json
{
  "clarification_events": [
    {
      "question": "",
      "reported_to": "main_window",
      "decision_source": "PRD/ARCH/TODO|user|timeout_fallback",
      "decision": "",
      "timestamp": ""
    }
  ],
  "timeout_fallbacks": [
    {
      "question": "",
      "timeout_minutes": 30,
      "fallback_instruction": "",
      "source_docs": ["PRD.md", "ARCH.md"]
    }
  ]
}
```

Do not place review conclusions here. Review conclusions belong in review artifacts or final reporting.
