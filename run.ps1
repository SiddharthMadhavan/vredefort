$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$desktopPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $desktopPython) {
    & $desktopPython main.py
} else {
    py -3.13 main.py
}
