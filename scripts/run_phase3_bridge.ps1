[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Host = "127.0.0.1",
    [int]$Port = 7007,
    [double]$StateHz = 60.0
)

$ErrorActionPreference = "Stop"
$xmlPath = Join-Path $ProjectRoot "outputs\mjcf\phase2_box_drop.xml"
$logPath = Join-Path $ProjectRoot "outputs\reports\phase3\bridge.jsonl"
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf)) {
    throw "Missing MJCF: $xmlPath"
}

$logDirectory = Split-Path -Parent $logPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

& $pythonPath -X utf8 -m replica_physics_twin.bridge_server `
    --xml $xmlPath `
    --host $Host `
    --port $Port `
    --state-hz $StateHz `
    --log $logPath
