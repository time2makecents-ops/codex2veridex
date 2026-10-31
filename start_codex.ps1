[CmdletBinding()]
param(
    [switch]$PrintRoute,
    [string]$RouteConfigFile = "",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArguments
)

$ErrorActionPreference = "Stop"

$workspace = $PSScriptRoot
$codexConfig = if ($RouteConfigFile) {
    $RouteConfigFile
} elseif ($env:CODEX_HOME) {
    Join-Path $env:CODEX_HOME "config.toml"
} else {
    Join-Path $env:USERPROFILE ".codex\config.toml"
}

$requiredFiles = @(
    $codexConfig,
    (Join-Path $workspace "AGENTS.md"),
    (Join-Path $workspace "DEVELOPMENT_MODEL_POLICY.md")
)

foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required Codex configuration file was not found: $path"
    }
}

function Get-TopLevelTomlString {
    param([string]$Path, [string]$Key)
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*=\s*["'']([^"'']+)["'']'
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^\s*\[') { break }
        if ($line -match $pattern) { return $Matches[1].Trim() }
    }
    return ""
}

function Remove-RouteQuotes {
    param([string]$Value)
    return ($Value.Trim() -replace '^["'']|["'']$', '')
}

$configuredModel = Get-TopLevelTomlString -Path $codexConfig -Key "model"
$configuredReasoning = Get-TopLevelTomlString -Path $codexConfig -Key "model_reasoning_effort"
$routeSource = "config.toml"

$profileName = ""
for ($index = 0; $index -lt $CodexArguments.Count; $index++) {
    $argument = [string]$CodexArguments[$index]
    if ($argument -in @("--profile", "-p") -and $index + 1 -lt $CodexArguments.Count) {
        $profileName = Remove-RouteQuotes ([string]$CodexArguments[++$index])
    } elseif ($argument -match '^--profile=(.+)$') {
        $profileName = Remove-RouteQuotes $Matches[1]
    }
}

if ($profileName) {
    if ($profileName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        throw "Codex profile name is invalid: $profileName"
    }
    $profileConfig = Join-Path (Split-Path -Parent $codexConfig) "$profileName.config.toml"
    if (-not (Test-Path -LiteralPath $profileConfig -PathType Leaf)) {
        throw "Codex profile configuration was not found: $profileConfig"
    }
    $profileModel = Get-TopLevelTomlString -Path $profileConfig -Key "model"
    $profileReasoning = Get-TopLevelTomlString -Path $profileConfig -Key "model_reasoning_effort"
    if ($profileModel) { $configuredModel = $profileModel }
    if ($profileReasoning) { $configuredReasoning = $profileReasoning }
    $routeSource = "profile $profileName"
}

for ($index = 0; $index -lt $CodexArguments.Count; $index++) {
    $argument = [string]$CodexArguments[$index]
    if ($argument -in @("--model", "-m") -and $index + 1 -lt $CodexArguments.Count) {
        $configuredModel = Remove-RouteQuotes ([string]$CodexArguments[++$index])
        $routeSource = "explicit CLI override"
        continue
    }
    if ($argument -match '^--model=(.+)$') {
        $configuredModel = Remove-RouteQuotes $Matches[1]
        $routeSource = "explicit CLI override"
        continue
    }
    $configOverride = ""
    if ($argument -in @("--config", "-c") -and $index + 1 -lt $CodexArguments.Count) {
        $configOverride = [string]$CodexArguments[++$index]
    } elseif ($argument -match '^--config=(.+)$') {
        $configOverride = $Matches[1]
    }
    if ($configOverride -match '^model=(.+)$') {
        $configuredModel = Remove-RouteQuotes $Matches[1]
        $routeSource = "explicit CLI override"
    } elseif ($configOverride -match '^model_reasoning_effort=(.+)$') {
        $configuredReasoning = Remove-RouteQuotes $Matches[1]
        $routeSource = "explicit CLI override"
    }
}

if (-not $configuredModel -or -not $configuredReasoning) {
    throw "Codex model and model_reasoning_effort must be explicit in $codexConfig or the launcher arguments."
}

$env:VERIDEX_CODEX_CONFIGURED_MODEL = $configuredModel
$env:VERIDEX_CODEX_CONFIGURED_REASONING = $configuredReasoning
$env:VERIDEX_CODEX_ROUTE_SOURCE = $routeSource

if ($PrintRoute) {
    [pscustomobject]@{
        model = $configuredModel
        reasoning = $configuredReasoning
        source = $routeSource
    } | ConvertTo-Json -Compress
    return
}

$codex = Get-Command codex -ErrorAction Stop
Write-Host "Starting a fresh Codex session in $workspace"
Write-Host "Personal rules: $codexConfig"
Write-Host "Workspace rules: $(Join-Path $workspace 'AGENTS.md')"
Write-Host "Configured terminal route: $configuredModel / $configuredReasoning ($routeSource)"
Write-Warning "Codex permissions: danger-full-access; approval prompts: disabled."

& $codex.Source `
    -C $workspace `
    --sandbox danger-full-access `
    --ask-for-approval never `
    @CodexArguments
