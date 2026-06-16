# ADworkflo Codegraph Design

Codegraph is a project-local code relationship index. It is not a prompt dump.

Its purpose:

> Let agents read less irrelevant code by querying definitions, dependencies, tests, call chains, and impact surfaces.

## Levels

### L0: rg + Manual Manifest

Use for small projects.

Inputs:

- File tree.
- `rg` searches.
- Human/agent-written `context_manifest`.

Supported questions:

- Which files mention this symbol?
- Where is this route/function probably located?
- Which tests look related?

### L1: Symbol / Import / Test Index

Use for medium projects.

Index:

- Files.
- Symbols: functions, classes, methods, routes when easy to detect.
- Imports.
- Test file mapping.

Supported queries:

```text
find_definition(symbol)
find_importers(file_or_module)
tests_for(file_or_symbol)
summarize_file(file, budget)
```

### L2: Full Codegraph

Use for large projects.

Index:

- Files, modules, symbols, routes, commands, tests.
- Defines/imports/references/calls/tested_by/depends_on edges.

Supported queries:

```text
find_definition(symbol)
find_references(symbol)
callers(function)
callees(function)
impacted_files(file)
tests_for(symbol_or_file)
get_slice(entrypoint, depth=2)
```

## Minimal Storage Model

Use SQLite or JSONL.

```sql
files(path, language, hash, loc, last_indexed_at)
nodes(id, type, name, file_path, start_line, end_line, signature, metadata_json)
edges(source_id, target_id, type, metadata_json)
```

## Project Flow

```text
task_spec
-> codegraph or rg query
-> context_manifest
-> worker reads scoped files
-> verification_result
```

## Fallback Rule

If codegraph is missing or stale:

1. Use `rg`.
2. Read file tree.
3. Build a manual `context_manifest`.
4. Record the limitation in `worker_state` or `verification_result`.

