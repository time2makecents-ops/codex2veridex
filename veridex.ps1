param(
  [ValidateSet("start", "stop", "restart", "status", "tailscale", "google-profile", "google-status", "instagram-profile", "instagram-login", "instagram-status", "facebook-profile", "facebook-login", "facebook-status", "gmail-connect", "gmail-status")]
  [string]$Action = "start",
  [switch]$NoBrowser,
  [switch]$FullAccess,
  [switch]$ReadOnly
)

$ErrorActionPreference = "Stop"
if ($FullAccess -and $ReadOnly) {
  throw "Choose either -FullAccess or -ReadOnly, not both. Full access is already the default."
}
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $RepoRoot ".runtime"
$LogRoot = Join-Path $RuntimeRoot "logs"
$PidPath = Join-Path $RuntimeRoot "veridex.pid"
$Port = if ($env:VERIDEX_PORT) { [int]$env:VERIDEX_PORT } else { 8765 }
$HealthUrl = "http://127.0.0.1:$Port/health"
$RequestedAccessMode = if ($ReadOnly) { "read_only" } else { "full" }

function Get-AccessStatus {
  try {
    return Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2
  } catch {
    return $null
  }
}

function Get-VeridexProcess {
  if (-not (Test-Path -LiteralPath $PidPath)) { return $null }
  $SavedPid = (Get-Content -LiteralPath $PidPath -Raw).Trim()
  if ($SavedPid -notmatch '^\d+$') { return $null }
  return Get-Process -Id ([int]$SavedPid) -ErrorAction SilentlyContinue
}

function Stop-VeridexProcessTree {
  param([int]$ProcessId)
  $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
  foreach ($Child in $Children) {
    Stop-VeridexProcessTree -ProcessId ([int]$Child.ProcessId)
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-Veridex {
  $Process = Get-VeridexProcess
  if ($Process) {
    Stop-VeridexProcessTree -ProcessId $Process.Id
    $Process.WaitForExit()
    Write-Host "Stopped standalone Veridex (PID $($Process.Id))."
  } else {
    Write-Host "Standalone Veridex is not running."
  }
  if (Test-Path -LiteralPath $PidPath) { Remove-Item -LiteralPath $PidPath -Force }
}

function Normalize-ProcessPathEnvironment {
  # Some launchers inject both Path and PATH. Start-Process treats environment
  # keys case-insensitively on Windows and throws before starting the child.
  $PathEntries = @(
    [Environment]::GetEnvironmentVariables("Process").GetEnumerator() |
      Where-Object { ([string]$_.Key) -ieq "Path" }
  )
  if ($PathEntries.Count -le 1) { return }
  $PathValue = [string]$PathEntries[0].Value
  foreach ($Entry in $PathEntries) {
    [Environment]::SetEnvironmentVariable([string]$Entry.Key, $null, "Process")
  }
  [Environment]::SetEnvironmentVariable("Path", $PathValue, "Process")
}

function Start-Veridex {
  $Existing = Get-VeridexProcess
  if ($Existing) {
    $CurrentStatus = Get-AccessStatus
    if ($CurrentStatus -and $CurrentStatus.access_mode -ne $RequestedAccessMode) {
      $RequestedLabel = if ($RequestedAccessMode -eq "full") { "full computer access" } else { "read-only computer access" }
      Write-Host "Restarting Veridex to enable $RequestedLabel."
      Stop-Veridex
    } else {
      $CurrentLabel = if ($CurrentStatus) { $CurrentStatus.access_label } else { "access mode unavailable" }
      Write-Host "Standalone Veridex is already running at http://127.0.0.1:$Port ($CurrentLabel)."
      if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
      return
    }
  }
  New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
  $EnvironmentPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $EnvironmentPython)) {
    Write-Warning "Resume Studio document support is not installed. Run .\scripts\setup.ps1 for DOCX and PDF exports."
  }
  $Python = if (Test-Path -LiteralPath $EnvironmentPython) { $EnvironmentPython } else { (Get-Command python -ErrorAction Stop).Source }
  $Server = Join-Path $RepoRoot "veridex_server.py"
  $PreviousAccessMode = $env:VERIDEX_CODEX_ACCESS_MODE
  $env:VERIDEX_CODEX_ACCESS_MODE = $RequestedAccessMode
  Normalize-ProcessPathEnvironment
  $Process = Start-Process -FilePath $Python `
    -ArgumentList @($Server, "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogRoot "server.out.log") `
    -RedirectStandardError (Join-Path $LogRoot "server.err.log") `
    -PassThru
  if ($null -eq $PreviousAccessMode) { Remove-Item Env:VERIDEX_CODEX_ACCESS_MODE -ErrorAction SilentlyContinue }
  else { $env:VERIDEX_CODEX_ACCESS_MODE = $PreviousAccessMode }
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
  $AccessLabel = if ($RequestedAccessMode -eq "full") { "FULL COMPUTER ACCESS" } else { "read-only computer access" }
  Write-Host "Standalone Veridex is running at http://127.0.0.1:$Port (PID $($Process.Id), $AccessLabel)."
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
}

function Enable-TailscaleAccess {
  $OpenBrowser = -not $NoBrowser
  $NoBrowser = $true
  Start-Veridex
  $Tailscale = (Get-Command tailscale -ErrorAction Stop).Source
  & $Tailscale serve --bg "http://127.0.0.1:$Port"
  if ($LASTEXITCODE -ne 0) { throw "Tailscale Serve could not expose Veridex to your private tailnet." }
  $Status = (& $Tailscale status --json | ConvertFrom-Json)
  $DnsName = ([string]$Status.Self.DNSName).TrimEnd('.')
  if (-not $DnsName) { throw "Tailscale did not report a private DNS name for this computer." }
  $RemotePath = Join-Path $RepoRoot "data\system\remote_access.json"
  if (-not (Test-Path -LiteralPath $RemotePath)) { throw "Veridex did not create its remote pairing token." }
  $Remote = Get-Content -LiteralPath $RemotePath -Raw | ConvertFrom-Json
  $PairUrl = "https://$DnsName/pair?token=$($Remote.pairing_token)"
  Write-Host "Private phone access is ready at https://$DnsName/"
  Write-Host "Open this one-time pairing URL on your phone: $PairUrl"
  if ($OpenBrowser) { Start-Process $PairUrl }
}

switch ($Action) {
  "start" { Start-Veridex }
  "stop" { Stop-Veridex }
  "restart" { Stop-Veridex; Start-Veridex }
  "status" {
    $Process = Get-VeridexProcess
    if ($Process) {
      $CurrentStatus = Get-AccessStatus
      $CurrentLabel = if ($CurrentStatus) { $CurrentStatus.access_label } else { "access mode unavailable" }
      Write-Host "Standalone Veridex is running at http://127.0.0.1:$Port (PID $($Process.Id), $CurrentLabel)."
    }
    else { Write-Host "Standalone Veridex is not running." }
  }
  "tailscale" { Enable-TailscaleAccess }
  "google-profile" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "google_chrome_search.js"
    & $Node $Bridge setup
    Write-Host "A dedicated Chrome window is ready. Sign in only as veridexcorp@gmail.com, then leave or close the window."
  }
  "google-status" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "google_chrome_search.js"
    & $Node $Bridge status
  }
  "instagram-profile" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "instagram_chrome_bridge.js"
    & $Node $Bridge setup
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "A dedicated Instagram Chrome window is ready. Its session is kept locally outside Git."
  }
  "instagram-login" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "instagram_chrome_bridge.js"
    & $Node $Bridge login
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  "instagram-status" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "instagram_chrome_bridge.js"
    & $Node $Bridge status
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  "facebook-profile" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "facebook_chrome_bridge.js"
    & $Node $Bridge setup
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "A dedicated Facebook Chrome window is ready. Its session is kept locally outside Git."
  }
  "facebook-login" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "facebook_chrome_bridge.js"
    & $Node $Bridge login
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  "facebook-status" {
    $Node = (Get-Command node -ErrorAction Stop).Source
    $Bridge = Join-Path $RepoRoot "facebook_chrome_bridge.js"
    & $Node $Bridge status
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
  "gmail-connect" {
    $Python = (Get-Command python -ErrorAction Stop).Source
    & $Python (Join-Path $RepoRoot "gmail_oauth.py")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Restart Veridex to load the refreshed Gmail connection."
  }
  "gmail-status" {
    $Python = (Get-Command python -ErrorAction Stop).Source
    & $Python -c "import json; from gmail_gateway import GmailGateway; print(json.dumps(GmailGateway().connection_status(), indent=2))"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
}
