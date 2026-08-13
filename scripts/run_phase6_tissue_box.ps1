[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 7007,
    [double]$StateHz = 60.0
)

$ErrorActionPreference = "Stop"
$xmlPath = Join-Path $ProjectRoot "outputs\mjcf\office0_tissue_box.xml"
$logPath = Join-Path $ProjectRoot "outputs\reports\phase6\bridge.jsonl"
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf)) {
    throw "Missing Phase 6 MJCF: $xmlPath. Run scripts\build_office0_tissue_box.py first."
}

$logDirectory = Split-Path -Parent $logPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

& $pythonPath -X utf8 -m replica_physics_twin.bridge_server `
    --xml $xmlPath `
    --host $ListenHost `
    --port $Port `
    --state-hz $StateHz `
    --log $logPath
