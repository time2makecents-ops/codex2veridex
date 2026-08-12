param(
  [ValidateSet("start", "stop", "restart", "status")]
  [string]$Action = "start",
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $RepoRoot ".runtime"
$LogRoot = Join-Path $RuntimeRoot "logs"
$PidPath = Join-Path $RuntimeRoot "veridex.pid"
$Port = if ($env:VERIDEX_PORT) { [int]$env:VERIDEX_PORT } else { 8765 }
$HealthUrl = "http://127.0.0.1:$Port/health"

function Get-VeridexProcess {
  if (-not (Test-Path -LiteralPath $PidPath)) { return $null }
  $SavedPid = (Get-Content -LiteralPath $PidPath -Raw).Trim()
  if ($SavedPid -notmatch '^\d+$') { return $null }
  return Get-Process -Id ([int]$SavedPid) -ErrorAction SilentlyContinue
}

function Stop-Veridex {
  $Process = Get-VeridexProcess
  if ($Process) {
    Stop-Process -Id $Process.Id -Force
    $Process.WaitForExit()
    Write-Host "Stopped standalone Veridex (PID $($Process.Id))."
  } else {
    Write-Host "Standalone Veridex is not running."
  }
  if (Test-Path -LiteralPath $PidPath) { Remove-Item -LiteralPath $PidPath -Force }
}

function Start-Veridex {
  $Existing = Get-VeridexProcess
  if ($Existing) {
    Write-Host "Standalone Veridex is already running at http://127.0.0.1:$Port"
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
    return
  }
  New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
  $Python = (Get-Command python -ErrorAction Stop).Source
  $Server = Join-Path $RepoRoot "veridex_server.py"
  $Process = Start-Process -FilePath $Python `
    -ArgumentList @($Server, "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogRoot "server.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "server.err.log") `
    -PassThru
  Set-Content -LiteralPath $PidPath -Value $Process.Id -Encoding ascii
  $Ready = $false
  for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    try {
      $Response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2
      if ($Response.StatusCode -eq 200) { $Ready = $true; break }
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not $Ready) {
    throw "Standalone Veridex did not become ready. See $LogRoot"
  }
  Write-Host "Standalone Veridex is running at http://127.0.0.1:$Port (PID $($Process.Id))."
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
}

switch ($Action) {
  "start" { Start-Veridex }
  "stop" { Stop-Veridex }
  "restart" { Stop-Veridex; Start-Veridex }
  "status" {
    $Process = Get-VeridexProcess
    if ($Process) { Write-Host "Standalone Veridex is running at http://127.0.0.1:$Port (PID $($Process.Id))." }
    else { Write-Host "Standalone Veridex is not running." }
  }
}
