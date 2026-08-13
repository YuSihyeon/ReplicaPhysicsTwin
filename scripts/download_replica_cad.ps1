[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [string]$DatasetRoot = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
if ([string]::IsNullOrWhiteSpace($DatasetRoot)) {
    $DatasetRoot = Join-Path $projectPath 'data\raw\replica_cad'
}
$datasetPath = [System.IO.Path]::GetFullPath($DatasetRoot)
$datasetUrl = 'https://huggingface.co/datasets/ai-habitat/ReplicaCAD_dataset.git'
$validator = Join-Path $projectPath 'scripts\verify_replica_cad.py'
$reportDir = Join-Path $projectPath 'outputs\reports'
$reportPath = Join-Path $reportDir 'replica_cad_validation.json'

New-Item -ItemType Directory -Path $reportDir -Force | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $datasetPath '.git') -PathType Container)) {
    if (Test-Path -LiteralPath $datasetPath) {
        $existing = Get-ChildItem -LiteralPath $datasetPath -Force | Select-Object -First 1
        if ($null -ne $existing) {
            throw "Dataset directory exists but is not an empty ReplicaCAD checkout: $datasetPath"
        }
    } else {
        New-Item -ItemType Directory -Path $datasetPath -Force | Out-Null
    }
    Write-Output "Cloning official ReplicaCAD dataset into $datasetPath"
    & git clone --depth 1 $datasetUrl $datasetPath
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Output "ReplicaCAD checkout already exists; fetching latest tracked pointers"
    & git -C $datasetPath fetch --depth 1 origin main
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch failed with exit code $LASTEXITCODE"
    }
    & git -C $datasetPath reset --hard origin/main
    if ($LASTEXITCODE -ne 0) {
        throw "git reset failed with exit code $LASTEXITCODE"
    }
}

& git -C $datasetPath lfs pull
if ($LASTEXITCODE -ne 0) {
    throw "git lfs pull failed with exit code $LASTEXITCODE"
}

$env:PYTHONPATH = Join-Path $projectPath 'src'
& python $validator --dataset-root $datasetPath --scene apt_0 --json-out $reportPath
if ($LASTEXITCODE -ne 0) {
    throw "ReplicaCAD validation failed. See $reportPath"
}

Write-Output "ReplicaCAD download and validation completed. Report: $reportPath"
