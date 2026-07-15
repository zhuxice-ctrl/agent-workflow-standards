param()

$ErrorActionPreference = "Stop"
$SkillRoot = $env:ADWORKFLO_SKILL_ROOT
if ([string]::IsNullOrWhiteSpace($SkillRoot)) {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $SkillRoot = Join-Path $env:CODEX_HOME "skills\adworkflo"
  } else {
    $SkillRoot = "F:\CodexHome\skills\ADworkflo"
  }
}

$ProviderRoot = Join-Path $SkillRoot "providers\typescript"
npm install --prefix $ProviderRoot --ignore-scripts
