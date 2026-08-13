$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\download_replica_office0.ps1'
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
    throw "Download script has parse errors: $($parseErrors -join '; ')"
}
$projectParameter = $ast.ParamBlock.Parameters | Where-Object {
    $_.Name.VariablePath.UserPath -eq 'ProjectRoot'
}
if ($null -eq $projectParameter) {
    throw 'ProjectRoot parameter is missing'
}
if ($projectParameter.DefaultValue.Extent.Text -match '\$PSScriptRoot') {
    throw 'ProjectRoot default must not reference PSScriptRoot during param binding'
}
Write-Output 'Download script startup path test: PASS'
