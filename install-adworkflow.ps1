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
  $ProviderRuntime = Join-Path $Target "providers\typescript\node_modules"
  if (Test-Path -LiteralPath $ProviderRuntime) {
    $ResolvedTarget = [System.IO.Path]::GetFullPath($Target).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    $ResolvedRuntime = [System.IO.Path]::GetFullPath($ProviderRuntime)
    if (-not $ResolvedRuntime.StartsWith($ResolvedTarget + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove provider runtime outside installed skill: $ResolvedRuntime"
    }
    Remove-Item -LiteralPath $ResolvedRuntime -Recurse -Force
  }
  Write-Output "installed: $Target"
}

$AdworkfloRoot = Join-Path $TargetSkills "adworkflo"
$SchemaSource = Join-Path $RepoRoot "schemas"
$SchemaTarget = Join-Path $AdworkfloRoot "schemas"
if (Test-Path -LiteralPath $SchemaSource) {
  New-Item -ItemType Directory -Path $SchemaTarget -Force | Out-Null
  Get-ChildItem -LiteralPath $SchemaSource -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $SchemaTarget -Force
  }
  Write-Output "installed-schemas: $SchemaTarget"
}

if ($SetUserEnv) {
  [Environment]::SetEnvironmentVariable("CODEX_HOME", $CodexHome, "User")
  [Environment]::SetEnvironmentVariable("ADWORKFLO_SKILL_ROOT", $AdworkfloRoot, "User")
  Write-Output "set-user-env: CODEX_HOME=$CodexHome"
  Write-Output "set-user-env: ADWORKFLO_SKILL_ROOT=$AdworkfloRoot"
}

Write-Output "done"
