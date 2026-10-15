$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$headers = @{
    Accept = 'application/vnd.github+json'
    'User-Agent' = 'FishingMacro-Installer'
    'X-GitHub-Api-Version' = '2022-11-28'
}

$repo = 'https://api.github.com/repos/dragonballls/Fishing-Macro'
$releases = Invoke-RestMethod -Uri "$repo/releases?per_page=100" -Headers $headers
$release = $releases |
    Where-Object { $_.tag_name -like 'fishingmacro-*' -and -not $_.draft } |
    Sort-Object { [datetime]$_.created_at } -Descending |
    Select-Object -First 1

if (!$release) {
    throw 'No published FishingMacro Windows release was found.'
}

$asset = $release.assets |
    Where-Object { $_.name -eq 'FishingMacro.exe' } |
    Select-Object -First 1

if (!$asset -or $asset.size -lt 10000000) {
    throw 'The release does not contain a valid-size FishingMacro.exe.'
}
if ($asset.digest -notmatch '^sha256:[0-9a-fA-F]{64}$') {
    throw 'GitHub did not provide a valid SHA-256 digest; installation cancelled.'
}

$expectedHash = $asset.digest.Substring(7).ToLowerInvariant()
$downloads = Join-Path $HOME 'Downloads'
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
$temporaryExe = Join-Path $env:TEMP ('FishingMacro-update-' + [guid]::NewGuid().ToString('N') + '.exe')
$target = Join-Path $downloads 'FishingMacro.exe'
$backup = $null
$replacementStarted = $false
$wasRunning = $false

try {
    Write-Host "Downloading public GitHub release $($release.tag_name)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $temporaryExe -UseBasicParsing -Headers @{
        'User-Agent' = 'FishingMacro-Installer'
    }

    $downloaded = Get-Item -LiteralPath $temporaryExe
    if ($downloaded.Length -ne [long]$asset.size) {
        throw "Download size mismatch ($($downloaded.Length) bytes); installation cancelled."
    }

    $actualHash = (Get-FileHash -LiteralPath $temporaryExe -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw 'SHA-256 verification failed; installation cancelled.'
    }

    $stream = [IO.File]::OpenRead($temporaryExe)
    try {
        if ($stream.ReadByte() -ne 77 -or $stream.ReadByte() -ne 90) {
            throw 'Downloaded file is not a valid Windows executable.'
        }
    }
    finally {
        $stream.Dispose()
    }

    Write-Host 'PASS: Download size, GitHub SHA-256 digest, and EXE header verified.'
    $wasRunning = $null -ne (Get-Process -Name FishingMacro -ErrorAction SilentlyContinue | Select-Object -First 1)
    Get-Process -Name FishingMacro -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2

    if (Test-Path -LiteralPath $target) {
        $backup = "$target.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Move-Item -LiteralPath $target -Destination $backup
    }

    $replacementStarted = $true
    Copy-Item -LiteralPath $temporaryExe -Destination $target

    $launched = Start-Process -FilePath $target -PassThru
    Start-Sleep -Seconds 12
    $launched.Refresh()
    if ($launched.HasExited) {
        throw "Updated app exited during startup (exit code $($launched.ExitCode))."
    }

    Write-Host ''
    Write-Host 'PASS: Updated Fishing Macro launched and remains running.'
    $launched | Select-Object Id, ProcessName, StartTime
    if ($backup) {
        Write-Host "Previous executable backup: $backup"
    }
}
catch {
    $failure = $_.Exception.Message

    if ($replacementStarted) {
        Get-Process -Name FishingMacro -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $target) {
            Remove-Item -LiteralPath $target -Force
        }
        if ($backup -and (Test-Path -LiteralPath $backup)) {
            Move-Item -LiteralPath $backup -Destination $target
            Write-Host 'The previous executable was restored.'
            if ($wasRunning) {
                Start-Process -FilePath $target -ErrorAction SilentlyContinue
            }
        }
    }
    elseif ($wasRunning -and (Test-Path -LiteralPath $target)) {
        Start-Process -FilePath $target -ErrorAction SilentlyContinue
    }

    throw "Fishing Macro update failed: $failure"
}
finally {
    if (Test-Path -LiteralPath $temporaryExe) {
        Remove-Item -LiteralPath $temporaryExe -Force -ErrorAction SilentlyContinue
    }
}
