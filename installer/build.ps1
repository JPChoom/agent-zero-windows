<#
.SYNOPSIS
  Builds installer\dist\AgentZeroWindows-Setup.exe (and its SHA-256) with Go.

.DESCRIPTION
  The setup .exe embeds install.ps1, so rebuild it whenever install.ps1
  changes. Needs Go 1.22 or later; no other tools and no downloads (the
  program uses only Go's standard library). The .exe is not code-signed, so
  Windows SmartScreen will warn on first run until it is.
#>
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$go = (Get-Command go -ErrorAction SilentlyContinue).Source
if (-not $go) { $go = "C:\Program Files\Go\bin\go.exe" }
if (-not (Test-Path $go)) { throw "Go not found. Install it from https://go.dev/dl/ and run this again." }

$dist = Join-Path $here "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$exe = Join-Path $dist "AgentZeroWindows-Setup.exe"

Push-Location $here
try {
    $env:CGO_ENABLED = "0"; $env:GOOS = "windows"; $env:GOARCH = "amd64"; $env:GOFLAGS = "-mod=mod"
    & $go build -trimpath -ldflags "-s -w" -o $exe .
    if ($LASTEXITCODE -ne 0) { throw "go build failed." }
} finally { Pop-Location }

$hash = (Get-FileHash -Algorithm SHA256 $exe).Hash.ToLower()
Set-Content -Path "$exe.sha256" -Value "$hash  AgentZeroWindows-Setup.exe" -Encoding ASCII
Write-Host "Built $exe"
Write-Host "SHA-256 $hash"
