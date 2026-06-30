$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  python -m venv .venv
  .\.venv\Scripts\python -m pip install --upgrade pip
  .\.venv\Scripts\python -m pip install -e .
}

$env:PYTHONPATH = "src"
.\.venv\Scripts\python -m eztrans

