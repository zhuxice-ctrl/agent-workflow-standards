param(
  [string]$Project = (Get-Location).Path,
  [ValidateSet("auto", "l1", "l2")]
  [string]$Level = "auto",
  [switch]$RequireTypeScript
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

$argsList = @("-3", (Join-Path $SkillRoot "scripts\build_codegraph.py"), "--project", $Project, "--level", $Level)
if ($RequireTypeScript) {
  $argsList += "--require-typescript"
}
& py @argsList
