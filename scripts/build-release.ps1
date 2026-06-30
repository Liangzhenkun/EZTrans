$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = "0.1.1"
$portablePath = ".\release\EZTrans-$version-portable.zip"
$setupPath = ".\release\EZTrans-$version-setup.exe"
$localIsccPath = ".\tools\InnoSetup\ISCC.exe"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  python -m venv .venv
}

.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pip install pyinstaller

if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist") { Remove-Item ".\dist" -Recurse -Force }
if (Test-Path ".\release") { Remove-Item ".\release" -Recurse -Force }

.\.venv\Scripts\python -m PyInstaller .\eztrans.spec --noconfirm

New-Item -ItemType Directory -Path ".\release" -Force | Out-Null
$isccPath = $null
if (Test-Path $localIsccPath) {
  $isccPath = (Resolve-Path $localIsccPath).Path
} else {
  $iscc = Get-Command iscc -ErrorAction SilentlyContinue
  if ($iscc) {
    $isccPath = $iscc.Source
  }
}

if ($isccPath) {
  & $isccPath ".\installer\eztrans.iss"
  if (Test-Path $portablePath) {
    Remove-Item $portablePath -Force
  }
  if (-not (Test-Path $setupPath)) {
    throw "Installer build finished without producing $setupPath"
  }
  Write-Host "Installer created: $setupPath"
} else {
  Compress-Archive -Path ".\dist\EZTrans\*" -DestinationPath $portablePath -Force
  Write-Host "Inno Setup compiler not found. Portable ZIP was created as a fallback: $portablePath"
}
