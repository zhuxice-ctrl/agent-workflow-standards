param(
  [string]$Project = (Get-Location).Path,
  [ValidateSet("auto", "small", "medium", "large")]
  [string]$Mode = "auto",
  [switch]$Force,
  [switch]$SkipDocAnalysis
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
$script = Join-Path $SkillRoot "scripts\init_adworkflow.py"

$argsList = @("-3", $script, "--project", $Project, "--mode", $Mode)
if ($Force) {
  $argsList += "--force"
}
if ($SkipDocAnalysis) {
  $argsList += "--skip-doc-analysis"
}

& $python @argsList
