[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArguments
)

$ErrorActionPreference = "Stop"

$workspace = $PSScriptRoot
$codexConfig = if ($env:CODEX_HOME) {
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

$codex = Get-Command codex -ErrorAction Stop
Write-Host "Starting a fresh Codex session in $workspace"
Write-Host "Personal rules: $codexConfig"
Write-Host "Workspace rules: $(Join-Path $workspace 'AGENTS.md')"
Write-Warning "Codex permissions: danger-full-access; approval prompts: disabled."

& $codex.Source `
    -C $workspace `
    --sandbox danger-full-access `
    --ask-for-approval never `
    @CodexArguments
