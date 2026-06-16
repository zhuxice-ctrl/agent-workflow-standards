param(
  [string]$Project = (Get-Location).Path
)

$ErrorActionPreference = "Stop"

$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $SkillRoot = Join-Path $env:CODEX_HOME "skills\adworkflo"
  } else {
    $SkillRoot = "F:\CodexHome\skills\ADworkflo"
  }
}

py -3 (Join-Path $SkillRoot "scripts\build_codegraph.py") --project $Project
