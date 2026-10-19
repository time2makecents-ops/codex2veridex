param(
    [int]$Port = 8773,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$repository = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repository ".venv\Scripts\python.exe"
$application = Join-Path $repository "iphone_media_manager.py"
$database = Join-Path $repository "data\iphone_media\archive.sqlite3"
$url = "http://127.0.0.1:$Port"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Veridex Python was not found at $python"
}
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "The iPhone Media Manager was not found at $application"
}
if ($CheckOnly) {
    Write-Output "The iphone command is ready."
    Write-Output "App: $application"
    Write-Output "URL: $url"
    exit 0
}

function Test-IPhoneMediaReady {
    try {
        $response = Invoke-RestMethod -Uri "$url/api/status" -TimeoutSec 2
        return ($null -ne $response.database)
    } catch {
        return $false
    }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener -and -not (Test-IPhoneMediaReady)) {
    throw "Port $Port is already being used by another program. Start with: iphone -Port 8774"
}

if (-not $listener) {
    $databaseFolder = Split-Path -Parent $database
    New-Item -ItemType Directory -Force -Path $databaseFolder | Out-Null
    Start-Process `
        -FilePath $python `
        -ArgumentList @($application, "serve", $database, "--port", "$Port") `
        -WorkingDirectory $repository `
        -WindowStyle Hidden | Out-Null

    $deadline = [datetime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        if (Test-IPhoneMediaReady) { break }
    } while ([datetime]::UtcNow -lt $deadline)

    if (-not (Test-IPhoneMediaReady)) {
        throw "The iPhone Media Manager did not become ready at $url"
    }
}

if (-not $NoBrowser) {
    Start-Process $url | Out-Null
}
Write-Output "iPhone Media Manager: $url"
