param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("scan", "copy", "delete")]
    [string]$Action,
    [string]$LocatorBase64 = "",
    [string]$Destination = ""
)

$ErrorActionPreference = "Stop"

function Write-JsonResult($Value) {
    $Value | ConvertTo-Json -Depth 10 -Compress
}

function Get-Locator {
    if (-not $LocatorBase64) { return $null }
    $bytes = [Convert]::FromBase64String($LocatorBase64)
    return ([Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json)
}

function Get-IPhoneRoot {
    $shell = New-Object -ComObject Shell.Application
    $computer = $shell.Namespace(17)
    if ($null -eq $computer) { throw "Windows could not open This PC." }
    $device = @($computer.Items()) | Where-Object {
        $_.Name -match "iPhone" -or $_.Name -match "Apple.*Phone"
    } | Select-Object -First 1
    if ($null -eq $device) {
        throw "No unlocked, trusted iPhone is visible in Windows. Connect it by USB, unlock it, and choose Trust."
    }
    $folder = $device.GetFolder
    if ($null -eq $folder) { throw "Windows can see the iPhone but cannot open its storage." }
    return [pscustomobject]@{ Shell = $shell; Device = $device; Folder = $folder }
}

function Find-Child($Folder, [string]$Name) {
    return @($Folder.Items()) | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
}

function Resolve-ItemPath($RootFolder, $Segments) {
    $folder = $RootFolder
    $item = $null
    foreach ($segment in @($Segments)) {
        $item = Find-Child $folder ([string]$segment)
        if ($null -eq $item) { throw "The iPhone item is no longer present: $segment" }
        if ($segment -ne @($Segments)[-1]) {
            if (-not $item.IsFolder) { throw "The iPhone path is no longer a folder." }
            $folder = $item.GetFolder
        }
    }
    return $item
}

function Get-PortableSize($Item) {
    try {
        $value = $Item.ExtendedProperty("System.Size")
        if ($null -ne $value -and "$value") { return [int64]$value }
    } catch {}
    try {
        if ($Item.Size) { return [int64]$Item.Size }
    } catch {}
    return 0
}

function Get-PortableModified($Item) {
    try {
        $value = $Item.ModifyDate
        if ($value) { return ([datetime]$value).ToUniversalTime().ToString("o") }
    } catch {}
    return $null
}

function Find-DcimFolder($RootFolder) {
    $queue = New-Object System.Collections.Generic.Queue[object]
    $queue.Enqueue([pscustomobject]@{ Folder = $RootFolder; Depth = 0 })
    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        foreach ($item in @($current.Folder.Items())) {
            if (-not $item.IsFolder) { continue }
            if ($item.Name -eq "DCIM") { return $item.GetFolder }
            if ($current.Depth -lt 3) {
                $queue.Enqueue([pscustomobject]@{ Folder = $item.GetFolder; Depth = $current.Depth + 1 })
            }
        }
    }
    throw "The iPhone DCIM folder is not available. Keep the phone unlocked and try again."
}

function Scan-Folder($Folder, [string[]]$Segments, [System.Collections.Generic.List[object]]$Output) {
    $supported = @(".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".mov", ".mp4", ".m4v", ".3gp")
    foreach ($item in @($Folder.Items())) {
        $next = @($Segments) + @([string]$item.Name)
        if ($item.IsFolder) {
            Scan-Folder $item.GetFolder $next $Output
            continue
        }
        $extension = [IO.Path]::GetExtension([string]$item.Name).ToLowerInvariant()
        if ($supported -notcontains $extension) { continue }
        $kind = if (@(".mov", ".mp4", ".m4v", ".3gp") -contains $extension) { "video" } else { "photo" }
        $modified = Get-PortableModified $item
        $Output.Add([pscustomobject]@{
            relative_path = ($next -join "/")
            filename = [string]$item.Name
            size_bytes = Get-PortableSize $item
            modified_at = $modified
            captured_at = $modified
            media_kind = $kind
            source_locator = @{ segments = $next }
        })
    }
}

$root = Get-IPhoneRoot

if ($Action -eq "scan") {
    $dcim = Find-DcimFolder $root.Folder
    $items = New-Object System.Collections.Generic.List[object]
    Scan-Folder $dcim @("DCIM") $items
    Write-JsonResult @($items)
    exit 0
}

$locator = Get-Locator
if ($null -eq $locator -or $null -eq $locator.segments) { throw "A portable-device locator is required." }
$segments = @($locator.segments)
if ($segments.Count -lt 2 -or $segments[0] -ne "DCIM") { throw "Only inventoried DCIM items are authorized." }
$dcimFolder = Find-DcimFolder $root.Folder
$item = Resolve-ItemPath $dcimFolder $segments[1..($segments.Count - 1)]

if ($Action -eq "copy") {
    if (-not $Destination) { throw "A destination is required." }
    $destinationPath = [IO.Path]::GetFullPath($Destination)
    [IO.Directory]::CreateDirectory($destinationPath) | Out-Null
    $destinationFolder = $root.Shell.Namespace($destinationPath)
    if ($null -eq $destinationFolder) { throw "Windows could not open the staging destination." }
    $destinationFolder.CopyHere($item, 20)
    $copiedPath = Join-Path $destinationPath ([string]$item.Name)
    $expected = Get-PortableSize $item
    $deadline = [datetime]::UtcNow.AddMinutes(20)
    do {
        Start-Sleep -Milliseconds 400
        if (Test-Path -LiteralPath $copiedPath -PathType Leaf) {
            $length = (Get-Item -LiteralPath $copiedPath).Length
            if ($expected -eq 0 -or $length -eq $expected) { break }
        }
    } while ([datetime]::UtcNow -lt $deadline)
    if (-not (Test-Path -LiteralPath $copiedPath -PathType Leaf)) { throw "Windows did not finish copying the iPhone item." }
    $actual = (Get-Item -LiteralPath $copiedPath).Length
    if ($expected -gt 0 -and $actual -ne $expected) { throw "The copied iPhone file is incomplete." }
    Write-JsonResult @{ path = $copiedPath; size_bytes = $actual }
    exit 0
}

if ($Action -eq "delete") {
    $deleteVerb = @($item.Verbs()) | Where-Object {
        ($_.Name -replace "&", "").Trim() -match "^(Delete|Remove)$"
    } | Select-Object -First 1
    if ($null -eq $deleteVerb) {
        Write-JsonResult @{ deleted = $false; reason = "The iPhone driver does not expose direct deletion for this item." }
        exit 0
    }
    $deleteVerb.DoIt()
    Start-Sleep -Seconds 2
    try {
        $remaining = Resolve-ItemPath $dcimFolder $segments[1..($segments.Count - 1)]
        Write-JsonResult @{ deleted = $false; reason = "Windows requested deletion, but the item is still present. Delete it manually in Photos." }
    } catch {
        Write-JsonResult @{ deleted = $true; reason = $null }
    }
}
