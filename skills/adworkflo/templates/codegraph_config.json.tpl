{
  "project_size": "{{PROJECT_SIZE}}",
  "level": "{{CODEGRAPH_LEVEL}}",
  "context_strategy": "{{CONTEXT_STRATEGY}}",
  "include": {{INCLUDE_DIRS_JSON}},
  "exclude": [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    "coverage"
  ],
  "languages": {{LANGUAGES_JSON}},
  "test_patterns": [
    "tests",
    "__tests__",
    "*.test.*",
    "*.spec.*"
  ],
  "supported_queries": {{SUPPORTED_QUERIES_JSON}}
}
