param(
  [string]$Project = (Get-Location).Path,
  [Parameter(Mandatory = $true)]
  [string]$TaskId,
  [string]$ArtifactRoot = ""
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

$argsList = @("-3", (Join-Path $SkillRoot "scripts\codegraph_post_edit.py"), "--project", $Project, "--task-id", $TaskId)
if (-not [string]::IsNullOrWhiteSpace($ArtifactRoot)) {
  $argsList += @("--out", (Join-Path $ArtifactRoot "impact_report.json"))
}
& py @argsList
