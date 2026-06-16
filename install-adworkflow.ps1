param(
  [string]$CodexHome = "",
  [switch]$Force,
  [switch]$SetUserEnv
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($CodexHome)) {
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $CodexHome = $env:CODEX_HOME
  } else {
    $CodexHome = "F:\CodexHome"
  }
}

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceSkills = Join-Path $RepoRoot "skills"
$TargetSkills = Join-Path $CodexHome "skills"

if (-not (Test-Path -LiteralPath $SourceSkills)) {
  throw "Source skills folder not found: $SourceSkills"
}

New-Item -ItemType Directory -Path $TargetSkills -Force | Out-Null

$SkillNames = @(
  "adworkflo",
  "arch-work",
  "todo-work",
  "artifact-driven-development"
)

foreach ($SkillName in $SkillNames) {
  $Source = Join-Path $SourceSkills $SkillName
  $Target = Join-Path $TargetSkills $SkillName

  if (-not (Test-Path -LiteralPath $Source)) {
    throw "Required skill is missing from repository: $Source"
  }

  if (Test-Path -LiteralPath $Target) {
    if ($Force) {
      Remove-Item -LiteralPath $Target -Recurse -Force
    } else {
      Write-Output "exists-skipped: $Target"
      continue
    }
  }

  Copy-Item -LiteralPath $Source -Destination $Target -Recurse
  Write-Output "installed: $Target"
}

$AdworkfloRoot = Join-Path $TargetSkills "adworkflo"

if ($SetUserEnv) {
  [Environment]::SetEnvironmentVariable("CODEX_HOME", $CodexHome, "User")
  [Environment]::SetEnvironmentVariable("ADWORKFLO_SKILL_ROOT", $AdworkfloRoot, "User")
  Write-Output "set-user-env: CODEX_HOME=$CodexHome"
  Write-Output "set-user-env: ADWORKFLO_SKILL_ROOT=$AdworkfloRoot"
}

Write-Output "done"
