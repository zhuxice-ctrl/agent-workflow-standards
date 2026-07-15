param(
  [string]$Project = (Get-Location).Path,
  [string]$Reviewer = ""
)

$ErrorActionPreference = "Stop"
$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  $SkillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME "skills\adworkflo" } else { "F:\CodexHome\skills\adworkflo" }
}

$script = Join-Path $SkillRoot "scripts\design_alignment.py"
if ([string]::IsNullOrWhiteSpace($Reviewer)) {
  py -3 $script --project $Project analyze
} else {
  py -3 $script --project $Project approve-semantic-review --reviewer $Reviewer
}
