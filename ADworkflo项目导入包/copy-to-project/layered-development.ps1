param(
  [string]$Project = (Get-Location).Path,
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  $SkillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME "skills\adworkflo" } else { "F:\CodexHome\skills\adworkflo" }
}

$argsList = @("-3", (Join-Path $SkillRoot "scripts\layered_development.py"), "--project", $Project)
if ($Force) { $argsList += "--force" }
py @argsList
