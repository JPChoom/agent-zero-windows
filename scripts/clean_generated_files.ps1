# Defaults to the repo root (the folder above scripts\).
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
Get-ChildItem $Root -Directory -Recurse -Force -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem $Root -File -Recurse -Force -Include *.pyc,*.pyo | Remove-Item -Force
Write-Host "Removed Python cache artifacts from $Root"
