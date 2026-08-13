[CmdletBinding()]
param(
    [string]$ProjectRoot = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
$downloadDir = Join-Path $projectPath 'data\downloads\replica_v1'
$sceneDir = Join-Path $projectPath 'data\raw\replica_v1\office_0'
$reportDir = Join-Path $projectPath 'outputs\reports'
$logPath = Join-Path $reportDir 'replica_download.log'
$reportPath = Join-Path $reportDir 'REPLICA_DOWNLOAD_REPORT.md'
$verifyScript = Join-Path $projectPath 'scripts\verify_replica_data.py'
$baseUrl = 'https://github.com/facebookresearch/Replica-Dataset/releases/download/v1.0'
$habitatUrl = 'https://dl.fbaipublicfiles.com/habitat/Replica/additional_habitat_configs.zip'
$habitatZip = Join-Path $downloadDir 'additional_habitat_configs.zip'
$habitatExpectedSize = 40793904L

$partSizes = [ordered]@{}
foreach ($letter in 'a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p') {
    $partSizes["replica_v1_0.tar.gz.parta$letter"] = 2000000000L
}
$partSizes['replica_v1_0.tar.gz.partaq'] = 1859047808L

New-Item -ItemType Directory -Path $downloadDir, $sceneDir, $reportDir -Force | Out-Null
Start-Transcript -Path $logPath -Append | Out-Null

try {
    $python = (& uv python find 3.11).Trim()
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "uv did not return an installed Python 3.11 interpreter: $python"
    }

    $remainingBytes = $habitatExpectedSize
    foreach ($entry in $partSizes.GetEnumerator()) {
        $path = Join-Path $downloadDir $entry.Key
        $actual = if (Test-Path -LiteralPath $path) { (Get-Item -LiteralPath $path).Length } else { 0L }
        if ($actual -gt $entry.Value) {
            throw "Local part is larger than the official asset: $path ($actual > $($entry.Value))"
        }
        $remainingBytes += $entry.Value - $actual
    }
    if (Test-Path -LiteralPath $habitatZip) {
        $habitatActual = (Get-Item -LiteralPath $habitatZip).Length
        if ($habitatActual -gt $habitatExpectedSize) {
            throw "Local Habitat ZIP is larger than the official asset: $habitatActual"
        }
        $remainingBytes -= [Math]::Min($habitatActual, $habitatExpectedSize)
    }

    $driveName = ([System.IO.Path]::GetPathRoot($downloadDir)).TrimEnd('\').TrimEnd(':')
    $freeBytes = (Get-PSDrive -Name $driveName).Free
    $reserveBytes = 20GB
    if ($freeBytes -lt ($remainingBytes + $reserveBytes)) {
        throw "Insufficient free space. Need remaining download plus 20 GiB reserve. Free=$freeBytes Remaining=$remainingBytes"
    }

    @(
        '# Replica Download Report',
        '',
        '- Status: **DOWNLOAD_IN_PROGRESS**',
        "- Started: $(Get-Date -Format o)",
        "- Download directory: ``$downloadDir``",
        "- Extracted scene directory: ``$sceneDir``",
        "- Remaining bytes at start: $remainingBytes",
        "- Free bytes at start: $freeBytes",
        '- Source: official Replica-Dataset v1.0 GitHub release',
        '- Resume: rerun `scripts\download_replica_office0.ps1`'
    ) | Set-Content -LiteralPath $reportPath -Encoding UTF8

    foreach ($entry in $partSizes.GetEnumerator()) {
        $name = $entry.Key
        $path = Join-Path $downloadDir $name
        if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -eq $entry.Value) {
            Write-Output "Already complete: $name"
            continue
        }
        $url = "$baseUrl/$name"
        Write-Output "Downloading/resuming: $name"
        & curl.exe --fail --location --continue-at - --retry 3 --retry-delay 5 --show-error --output $path $url
        if ($LASTEXITCODE -ne 0) {
            throw "curl failed for $name with exit code $LASTEXITCODE. Resume by rerunning this script."
        }
        $actualSize = (Get-Item -LiteralPath $path).Length
        if ($actualSize -ne $entry.Value) {
            throw "Size mismatch for $name. Expected=$($entry.Value) Actual=$actualSize"
        }
    }

    if (-not ((Test-Path -LiteralPath $habitatZip) -and (Get-Item -LiteralPath $habitatZip).Length -eq $habitatExpectedSize)) {
        Write-Output 'Downloading/resuming official supplemental Habitat configs'
        & curl.exe --fail --location --continue-at - --retry 3 --retry-delay 5 --show-error --output $habitatZip $habitatUrl
        if ($LASTEXITCODE -ne 0) {
            throw "curl failed for supplemental Habitat configs with exit code $LASTEXITCODE"
        }
    }
    if ((Get-Item -LiteralPath $habitatZip).Length -ne $habitatExpectedSize) {
        throw "Size mismatch for supplemental Habitat ZIP"
    }

    $env:PYTHONPATH = Join-Path $projectPath 'src'
    & $python $verifyScript parts --download-dir $downloadDir --json-out (Join-Path $reportDir 'replica_parts.json')
    if ($LASTEXITCODE -ne 0) { throw 'Replica archive part verification failed' }
    & $python $verifyScript extract --download-dir $downloadDir --scene-dir $sceneDir --json-out (Join-Path $reportDir 'replica_extract.json')
    if ($LASTEXITCODE -ne 0) { throw 'office_0 archive extraction failed' }
    & $python $verifyScript habitat --zip-path $habitatZip --scene-dir $sceneDir --json-out (Join-Path $reportDir 'replica_habitat_extract.json')
    if ($LASTEXITCODE -ne 0) { throw 'office_0 supplemental Habitat extraction failed' }
    & $python $verifyScript scene --scene-dir $sceneDir --json-out (Join-Path $reportDir 'replica_scene.json')
    if ($LASTEXITCODE -ne 0) { throw 'office_0 required-file verification failed' }
    & $python $verifyScript report --download-dir $downloadDir --scene-dir $sceneDir --report-path $reportPath
    if ($LASTEXITCODE -ne 0) { throw 'Final report indicates incomplete data' }
    Write-Output 'Replica office_0 download, extraction, and verification completed.'
}
catch {
    Add-Content -LiteralPath $reportPath -Encoding UTF8 -Value @(
        '',
        '## Failure',
        '',
        "- Time: $(Get-Date -Format o)",
        "- Error: $($_.Exception.Message)",
        '- Resume command: `powershell -ExecutionPolicy Bypass -File scripts\download_replica_office0.ps1`'
    )
    Write-Error $_
    exit 1
}
finally {
    Stop-Transcript | Out-Null
}
