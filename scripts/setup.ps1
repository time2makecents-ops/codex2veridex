param()

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentRoot = Join-Path $RepoRoot ".venv"
$Requirements = Join-Path $RepoRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $EnvironmentRoot)) {
  $SystemPython = (Get-Command python -ErrorAction Stop).Source
  & $SystemPython -m venv $EnvironmentRoot
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Python = Join-Path $EnvironmentRoot "Scripts\python.exe"
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Veridex document dependencies are ready in $EnvironmentRoot"
