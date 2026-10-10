$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $buildPython)) {
    throw 'Create the project .venv and install requirements-build.txt first.'
}
& $buildPython -m PyInstaller --noconfirm CityCollapse.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
Write-Output "Built: $PSScriptRoot/dist/CityCollapse.exe"
