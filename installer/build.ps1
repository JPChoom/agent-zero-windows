<#
.SYNOPSIS
  Builds the Windows installer programs with Go: AgentZero.exe (launcher with
  tray icon), Uninstall.exe and AgentZeroWindows-Setup.exe (which carries the
  other two and install.ps1), plus the SHA-256 of the setup .exe.

.DESCRIPTION
  Output goes to installer\dist\ (or -OutDir). Needs Go 1.22 or later; no other
  tools and no downloads (the programs use only Go's standard library). Rebuild
  whenever install.ps1, uninstall.ps1, agent-zero.ico or any program changes.
  The .exe files are not code-signed, so Windows SmartScreen warns on first run
  until they are.
#>
param([string]$OutDir = "")
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$go = (Get-Command go -ErrorAction SilentlyContinue).Source
if (-not $go) { $go = "C:\Program Files\Go\bin\go.exe" }
if (-not (Test-Path $go)) { throw "Go not found. Install it from https://go.dev/dl/ and run this again." }

$dist = if ($OutDir) { $OutDir } else { Join-Path $here "dist" }
New-Item -ItemType Directory -Force -Path $dist | Out-Null

function Stage($package, $files) {
    $assets = Join-Path $here "cmd\$package\assets"
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    foreach ($f in $files.GetEnumerator()) { Copy-Item -LiteralPath $f.Value -Destination (Join-Path $assets $f.Key) -Force }
}

function Build($package, $output, $gui) {
    $flags = if ($gui) { "-s -w -H windowsgui" } else { "-s -w" }
    & $go build -trimpath -ldflags $flags -o $output "./cmd/$package"
    if ($LASTEXITCODE -ne 0) { throw "go build ./cmd/$package failed." }
}

Push-Location $here
try {
    $env:CGO_ENABLED = "0"; $env:GOOS = "windows"; $env:GOARCH = "amd64"; $env:GOFLAGS = "-mod=mod"

    Stage "launcher"    @{ "agent-zero.ico" = (Join-Path $here "agent-zero.ico") }
    Stage "uninstaller" @{ "uninstall.ps1" = (Join-Path $here "uninstall.ps1") }
    Build "launcher"    (Join-Path $dist "AgentZero.exe") $true
    Build "uninstaller" (Join-Path $dist "Uninstall.exe") $false

    Stage "setup" @{
        "install.ps1"   = (Join-Path $here "install.ps1")
        "AgentZero.exe" = (Join-Path $dist "AgentZero.exe")
        "Uninstall.exe" = (Join-Path $dist "Uninstall.exe")
    }
    $setup = Join-Path $dist "AgentZeroWindows-Setup.exe"
    Build "setup" $setup $false
} finally { Pop-Location }

$hash = (Get-FileHash -Algorithm SHA256 $setup).Hash.ToLower()
Set-Content -Path "$setup.sha256" -Value "$hash  AgentZeroWindows-Setup.exe" -Encoding ASCII
Write-Host "Built $setup"
Write-Host "SHA-256 $hash"
