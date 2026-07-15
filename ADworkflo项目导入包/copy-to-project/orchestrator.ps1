param(
  [Parameter(Mandatory = $true)]
  [string]$RunId,
  [ValidateSet("start", "status", "ready", "resume")]
  [string]$Command = "status",
  [string]$Project = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  $SkillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME "skills\adworkflo" } else { "F:\CodexHome\skills\adworkflo" }
}

py -3 (Join-Path $SkillRoot "scripts\orchestrator.py") --project $Project --run-id $RunId $Command
