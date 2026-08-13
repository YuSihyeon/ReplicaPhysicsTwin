[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 7007,
    [double]$StateHz = 60.0
)

$ErrorActionPreference = "Stop"
$xmlPath = Join-Path $ProjectRoot "outputs\mjcf\office0_interaction.xml"
$physicalManifestPath = Join-Path $ProjectRoot "outputs\metadata\office0_physical_manifest.json"
$logPath = Join-Path $ProjectRoot "outputs\reports\interaction\bridge.jsonl"
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf)) {
    & $pythonPath -X utf8 (Join-Path $ProjectRoot "scripts\build_office0_interaction_scene.py")
}
if (-not (Test-Path -LiteralPath $physicalManifestPath -PathType Leaf)) {
    throw "Missing physical manifest: $physicalManifestPath"
}

$logDirectory = Split-Path -Parent $logPath
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$env:PYTHONPATH = Join-Path $ProjectRoot "src"

& $pythonPath -X utf8 -m replica_physics_twin.bridge_server `
    --xml $xmlPath `
    --physical-manifest $physicalManifestPath `
    --host $ListenHost `
    --port $Port `
    --state-hz $StateHz `
    --log $logPath
