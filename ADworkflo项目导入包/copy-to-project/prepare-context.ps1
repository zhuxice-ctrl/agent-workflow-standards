param(
  [string]$Project = (Get-Location).Path,
  [string]$Task = "",
  [switch]$NoBuildIndex,
  [ValidateSet("auto", "l1", "l2")]
  [string]$Level = "auto"
)

$ErrorActionPreference = "Stop"

$python = "py"
$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $SkillRoot = Join-Path $env:CODEX_HOME "skills\adworkflo"
  } else {
    $SkillRoot = "F:\CodexHome\skills\ADworkflo"
  }
}
$script = Join-Path $SkillRoot "scripts\prepare_context.py"

$argsList = @("-3", $script, "--project", $Project)
$argsList += @("--level", $Level)
if ($Task -ne "") {
  $argsList += @("--task", $Task)
}
if ($NoBuildIndex) {
  $argsList += "--no-build-index"
}

& $python @argsList
