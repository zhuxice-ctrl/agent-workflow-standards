param(
  [string]$Project = (Get-Location).Path,
  [string]$TaskRoot = ""
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

$argsList = @("-3", (Join-Path $SkillRoot "scripts\apply_context_expansion.py"), "--project", $Project)
if (-not [string]::IsNullOrWhiteSpace($TaskRoot)) {
  $argsList += @("--task-root", $TaskRoot)
}
& py @argsList
