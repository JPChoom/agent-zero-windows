param([string]$Root = "C:\a0")
$ErrorActionPreference = "Stop"
Get-ChildItem $Root -Directory -Recurse -Force -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem $Root -File -Recurse -Force -Include *.pyc,*.pyo | Remove-Item -Force
Write-Host "Removed Python cache artifacts from $Root"
