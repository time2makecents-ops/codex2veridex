param(
  [ValidateSet("start", "stop", "restart", "status", "tailscale", "lan", "intake", "google-profile", "google-status", "instagram-profile", "instagram-login", "instagram-status", "facebook-profile", "facebook-login", "facebook-status", "gmail-connect", "gmail-status")]
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
$LaunchPath = Join-Path $RuntimeRoot "veridex.launch.json"
$Port = if ($env:VERIDEX_PORT) { [int]$env:VERIDEX_PORT } else { 8765 }
$CompanionPort = 8775
$CompanionPidPath = Join-Path $RuntimeRoot "intake-companion.pid"
$CompanionHealthUrl = "http://127.0.0.1:$CompanionPort/health"
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
  # A launcher crash can leave an untracked Veridex server holding the configured
  # port. Reclaim only a listener that identifies itself as this server.
  $Listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  foreach ($Listener in $Listeners) {
    $ListenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($Listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($ListenerProcess -and [string]$ListenerProcess.CommandLine -match '(?i)(^|[\\/\s])veridex_server\.py(?:\s|$)') {
      Stop-VeridexProcessTree -ProcessId ([int]$Listener.OwningProcess)
      Write-Host "Stopped stale Veridex listener (PID $($Listener.OwningProcess))."
    }
  }
  if (Test-Path -LiteralPath $PidPath) { Remove-Item -LiteralPath $PidPath -Force }
  if (Test-Path -LiteralPath $LaunchPath) { Remove-Item -LiteralPath $LaunchPath -Force }
}

function Get-IntakeCompanionProcess {
  if (-not (Test-Path -LiteralPath $CompanionPidPath)) { return $null }
  $SavedPid = (Get-Content -LiteralPath $CompanionPidPath -Raw).Trim()
  if ($SavedPid -notmatch '^\d+$') { return $null }
  return Get-Process -Id ([int]$SavedPid) -ErrorAction SilentlyContinue
}

function Stop-IntakeCompanion {
  $Process = Get-IntakeCompanionProcess
  if ($Process) { Stop-VeridexProcessTree -ProcessId $Process.Id; $Process.WaitForExit() }
  if (Test-Path -LiteralPath $CompanionPidPath) { Remove-Item -LiteralPath $CompanionPidPath -Force }
}

function Start-IntakeCompanion {
  param([string]$ListenHost = "127.0.0.1")
  $Existing = Get-IntakeCompanionProcess
  if ($Existing) {
    try { if ((Invoke-WebRequest -Uri $CompanionHealthUrl -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { return } } catch { }
    Stop-IntakeCompanion
  }
  New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
  $EnvironmentPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  $Python = if (Test-Path -LiteralPath $EnvironmentPython) { $EnvironmentPython } else { (Get-Command python -ErrorAction Stop).Source }
  $Server = Join-Path $RepoRoot "intake_companion_server.py"
  Normalize-ProcessPathEnvironment
  $Process = Start-Process -FilePath $Python -ArgumentList @($Server, "--host", $ListenHost, "--port", "$CompanionPort") -WorkingDirectory $RepoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogRoot "intake-companion.out.log") -RedirectStandardError (Join-Path $LogRoot "intake-companion.err.log") -PassThru
  Set-Content -LiteralPath $CompanionPidPath -Value $Process.Id -Encoding ascii
  for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
    try { if ((Invoke-WebRequest -Uri $CompanionHealthUrl -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { return } } catch { Start-Sleep -Milliseconds 250 }
  }
  throw "Intake Companion did not become ready. See $LogRoot"
}

function Get-VeridexLaunch {
  if (-not (Test-Path -LiteralPath $LaunchPath)) { return $null }
  try { return Get-Content -LiteralPath $LaunchPath -Raw | ConvertFrom-Json } catch { return $null }
}

function Save-VeridexLaunch {
  param([string]$ListenHost, [bool]$AllowInsecureRemoteCookie)
  $launch = [ordered]@{
    host = $ListenHost
    port = $Port
    allow_insecure_remote_cookie = $AllowInsecureRemoteCookie
  }
  $temporary = "$LaunchPath.tmp"
  $launch | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding utf8
  Move-Item -LiteralPath $temporary -Destination $LaunchPath -Force
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

function Open-VeridexBrowser {
  param([string]$Url)
  $Node = (Get-Command node -ErrorAction Stop).Source
  $Bridge = Join-Path $RepoRoot "veridex_browser.js"
  & $Node $Bridge open $Url | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "The Veridex browser could not be opened." }
}

function Start-Veridex {
  param(
    [string]$ListenHost = "127.0.0.1",
    [switch]$AllowInsecureRemoteCookie
  )
  $Existing = Get-VeridexProcess
  if ($Existing) {
    $CurrentStatus = Get-AccessStatus
    $CurrentLaunch = Get-VeridexLaunch
    $LaunchMatches = $CurrentLaunch -and $CurrentLaunch.host -eq $ListenHost -and ([bool]$CurrentLaunch.allow_insecure_remote_cookie -eq [bool]$AllowInsecureRemoteCookie)
    if (($CurrentStatus -and $CurrentStatus.access_mode -ne $RequestedAccessMode) -or -not $LaunchMatches) {
      $RequestedLabel = if ($RequestedAccessMode -eq "full") { "full computer access" } else { "read-only computer access" }
      Write-Host "Restarting Veridex to enable $RequestedLabel with the requested network mode."
      Stop-Veridex
    } else {
      $CurrentLabel = if ($CurrentStatus) { $CurrentStatus.access_label } else { "access mode unavailable" }
      Write-Host "Standalone Veridex is already running at http://$ListenHost`:$Port ($CurrentLabel)."
      if (-not $NoBrowser) { Open-VeridexBrowser "http://127.0.0.1:$Port" }
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
  $Arguments = @($Server, "--host", $ListenHost, "--port", "$Port")
  if ($AllowInsecureRemoteCookie) { $Arguments += "--allow-insecure-remote-cookie" }
  $Process = Start-Process -FilePath $Python `
    -ArgumentList $Arguments `
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
  Save-VeridexLaunch -ListenHost $ListenHost -AllowInsecureRemoteCookie ([bool]$AllowInsecureRemoteCookie)
  $AccessLabel = if ($RequestedAccessMode -eq "full") { "FULL COMPUTER ACCESS" } else { "read-only computer access" }
  Write-Host "Standalone Veridex is running at http://$ListenHost`:$Port (PID $($Process.Id), $AccessLabel)."
  if (-not $NoBrowser) { Open-VeridexBrowser "http://127.0.0.1:$Port" }
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

function Get-PrivateLanIPv4Addresses {
  $aliases = @(
    Get-NetConnectionProfile -ErrorAction SilentlyContinue |
      Where-Object { $_.NetworkCategory -eq "Private" } |
      ForEach-Object { $_.InterfaceAlias }
  )
  if (-not $aliases) { return @() }
  return @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object {
        $_.InterfaceAlias -in $aliases -and
        $_.IPAddress -notmatch '^(127|169\.254)\.'
      } |
      ForEach-Object { $_.IPAddress } |
      Sort-Object -Unique
  )
}

function Enable-VeridexLanFirewall {
  $RuleName = "Veridex LAN $Port"
  try {
    $Existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
    if (-not $Existing) {
      New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -Profile Private -ErrorAction Stop | Out-Null
      Write-Host "Allowed Veridex on private networks only (Windows Firewall rule: $RuleName)."
    }
  } catch {
    Write-Warning "Veridex is listening on the LAN, but Windows Firewall could not add its private-network rule. If the phone cannot connect, allow TCP $Port for Private networks."
  }
}

function Enable-LanAccess {
  $OpenBrowser = -not $NoBrowser
  $NoBrowser = $true
  Start-Veridex -ListenHost "0.0.0.0" -AllowInsecureRemoteCookie
  Start-IntakeCompanion -ListenHost "0.0.0.0"
  Enable-VeridexLanFirewall
  $addresses = Get-PrivateLanIPv4Addresses
  if (-not $addresses) { throw "No private-network IPv4 address was found. Connect this PC and phone to the same private Wi-Fi, then run .\\veridex.ps1 lan again." }
  $RemotePath = Join-Path $RepoRoot "data\system\remote_access.json"
  if (-not (Test-Path -LiteralPath $RemotePath)) { throw "Veridex did not create its remote pairing token." }
  $Remote = Get-Content -LiteralPath $RemotePath -Raw | ConvertFrom-Json
  foreach ($Address in $addresses) {
    $PairUrl = "http://$Address`:$Port/pair?token=$($Remote.pairing_token)"
    Write-Host "Private-LAN phone pairing URL: $PairUrl"
    Write-Host "Phone Capture Companion: http://$Address`:$CompanionPort/"
  }
  Write-Warning "LAN mode uses HTTP on private Wi-Fi. Keep the pairing URL private and use .\\veridex.ps1 tailscale when away from home or on an untrusted network."
  if ($OpenBrowser) { Start-Process "http://127.0.0.1:$CompanionPort/" }
}

switch ($Action) {
  "start" { Start-Veridex }
  "stop" { Stop-IntakeCompanion; Stop-Veridex }
  "restart" { Stop-IntakeCompanion; Stop-Veridex; Start-Veridex }
  "status" {
    $Process = Get-VeridexProcess
    if ($Process) {
      $CurrentStatus = Get-AccessStatus
      $CurrentLabel = if ($CurrentStatus) { $CurrentStatus.access_label } else { "access mode unavailable" }
      $CurrentLaunch = Get-VeridexLaunch
      $CurrentHost = if ($CurrentLaunch -and $CurrentLaunch.host) { $CurrentLaunch.host } else { "127.0.0.1" }
      Write-Host "Standalone Veridex is running at http://$CurrentHost`:$Port (PID $($Process.Id), $CurrentLabel)."
    }
    else { Write-Host "Standalone Veridex is not running." }
  }
  "tailscale" { Enable-TailscaleAccess }
  "lan" { Enable-LanAccess }
  "intake" { Start-IntakeCompanion -ListenHost "0.0.0.0"; Start-Process "http://127.0.0.1:$CompanionPort/" }
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
