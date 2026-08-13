[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ListenHost = '127.0.0.1',
    [int]$Port = 7007,
    [double]$StateHz = 60.0
)

$ErrorActionPreference = 'Stop'
$projectPath = [System.IO.Path]::GetFullPath($ProjectRoot)
$datasetRoot = Join-Path $projectPath 'data\raw\replica_cad'
$outputRoot = Join-Path $projectPath 'outputs\replica_cad'
$xmlPath = Join-Path $outputRoot 'mjcf\replica_cad_apt_0_interaction.xml'
$manifestPath = Join-Path $outputRoot 'metadata\replica_cad_interaction.json'
$logPath = Join-Path $outputRoot 'reports\replica_cad_bridge.jsonl'
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $datasetRoot -PathType Container)) {
    throw "ReplicaCAD dataset is missing: $datasetRoot. Run scripts\download_replica_cad.ps1 first."
}
if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf) -or -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    $env:PYTHONPATH = Join-Path $projectPath 'src'
    & $pythonPath -X utf8 (Join-Path $projectPath 'scripts\build_replica_cad_pipeline.py') `
        --dataset-root $datasetRoot `
        --scene apt_0 `
        --output-root $outputRoot
    if ($LASTEXITCODE -ne 0) {
        throw "ReplicaCAD scene compilation failed with exit code $LASTEXITCODE"
    }
}

$logDirectory = Split-Path -Parent $logPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$env:PYTHONPATH = Join-Path $projectPath 'src'

& $pythonPath -X utf8 -m replica_physics_twin.bridge_server `
    --xml $xmlPath `
    --physical-manifest $manifestPath `
    --scene-id apt_0 `
    --host $ListenHost `
    --port $Port `
    --state-hz $StateHz `
    --log $logPath
