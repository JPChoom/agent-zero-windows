<#
.SYNOPSIS
  Installs Agent Zero for Windows for the current user (no admin rights).

.DESCRIPTION
  One supported configuration: Windows 11 x64 with Python 3.12 and Git.
  - Clones the chosen release tag of github.com/JPChoom/agent-zero-windows over
    HTTPS into %LOCALAPPDATA%\Programs\AgentZeroWindows (a git checkout, so the
    in-app updater with one-click roll back keeps working).
  - Creates .venv with Python 3.12 and installs requirements.lock.txt: the exact
    versions the release was tested with.
  - Adds a Start menu entry (tray launcher) and an entry in Settings > Apps so it
    can be uninstalled like any program. Your data lives in its usr\ folder; the
    uninstaller keeps it unless you choose a clean uninstall.

  Re-running it on an existing install updates it to the chosen tag (local
  changes are never overwritten: it stops instead).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -Version v1.4
#>
param(
    [string]$Version = "",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\AgentZeroWindows"),
    [switch]$NoShortcut,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Repo = "JPChoom/agent-zero-windows"
$RepoUrl = "https://github.com/$Repo.git"
$AppName = "Agent Zero for Windows"
$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentZeroWindows"

function Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "ERROR: $text" -ForegroundColor Red; exit 1 }

# --- the one supported configuration -------------------------------------
$os = Get-CimInstance Win32_OperatingSystem
if (-not $Force) {
    if ([int]$os.BuildNumber -lt 22000) { Fail "Windows 11 is required (this is build $($os.BuildNumber)). Use -Force to try anyway." }
    if (-not [Environment]::Is64BitOperatingSystem) { Fail "64-bit Windows is required." }
}

function Find-Python312 {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $p = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
    }
    foreach ($name in @("python3.12", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $candidates += $cmd.Source }
    }
    foreach ($exe in $candidates) {
        $v = (& $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $v.Trim() -eq "3.12") { return $exe }
    }
    return $null
}

Step "Checking Python 3.12 and Git"
$python = Find-Python312
if (-not $python) { Fail "Python 3.12 not found. Install it with:  winget install --id Python.Python.3.12 -e  then run this again." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "Git not found. Install it with:  winget install --id Git.Git -e  then run this again." }

# --- which release ------------------------------------------------------------
if (-not $Version) {
    Step "Finding the latest release"
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "agent-zero-windows-installer" }
    $Version = $release.tag_name
}
if ($Version -notmatch '^v\d+\.\d+(\.\d+)?$') { Fail "Not a release tag: $Version" }

# --- code ---------------------------------------------------------------------
$app = $InstallDir
if (Test-Path (Join-Path $app ".git")) {
    Step "Updating the existing install to $Version"
    Push-Location $app
    try {
        $dirty = (& git status --porcelain --untracked-files=no)
        if ($dirty) { Fail "The install has local changes; not touching it. ($app)" }
        & git fetch --quiet --tags origin
        if ($LASTEXITCODE -ne 0) { Fail "git fetch failed." }
        & git -c advice.detachedHead=false checkout --quiet "refs/tags/$Version"
        if ($LASTEXITCODE -ne 0) { Fail "Release $Version not found." }
    } finally { Pop-Location }
} else {
    if ((Test-Path $app) -and (Get-ChildItem $app -Force | Select-Object -First 1)) { Fail "$app exists and is not an Agent Zero install." }
    Step "Downloading $AppName $Version"
    & git clone --quiet --depth 1 --branch $Version $RepoUrl $app
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }
}

# --- Python environment ---------------------------------------------------------
$venvPython = Join-Path $app ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Step "Creating the Python environment"
    & $python -m venv (Join-Path $app ".venv")
    if ($LASTEXITCODE -ne 0) { Fail "Could not create .venv." }
}
$lock = Join-Path $app "requirements.lock.txt"
$reqs = if (Test-Path $lock) { $lock } else { Join-Path $app "requirements.txt" }
Step "Installing packages from $(Split-Path $reqs -Leaf) (this takes a while the first time)"
& $venvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
& $venvPython -m pip install --disable-pip-version-check --quiet -r $reqs
if ($LASTEXITCODE -ne 0) { Fail "Package installation failed. See the messages above." }

# --- Start menu and Apps entry ----------------------------------------------------
$pythonw = Join-Path $app ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $app "installer\tray_launcher.pyw"
if (-not $NoShortcut) {
    Step "Adding the Start menu entry"
    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $startMenu "$AppName.lnk"))
    $link.TargetPath = $pythonw
    $link.Arguments = "`"$launcher`""
    $link.WorkingDirectory = $app
    $icon = Join-Path $app "installer\agent-zero.ico"
    if (Test-Path $icon) { $link.IconLocation = $icon }
    $link.Description = $AppName
    $link.Save()
}

Step "Registering in Settings > Apps"
New-Item -Path $UninstallKey -Force | Out-Null
$uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$app\installer\uninstall.ps1`" -InstallDir `"$app`""
Set-ItemProperty -Path $UninstallKey -Name DisplayName -Value $AppName
Set-ItemProperty -Path $UninstallKey -Name DisplayVersion -Value $Version.TrimStart("v")
Set-ItemProperty -Path $UninstallKey -Name Publisher -Value "Agent Zero for Windows"
Set-ItemProperty -Path $UninstallKey -Name InstallLocation -Value $app
Set-ItemProperty -Path $UninstallKey -Name DisplayIcon -Value (Join-Path $app "installer\agent-zero.ico")
Set-ItemProperty -Path $UninstallKey -Name UninstallString -Value $uninstall
Set-ItemProperty -Path $UninstallKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $UninstallKey -Name NoRepair -Value 1 -Type DWord

Step "Done"
Write-Host "$AppName $Version is installed in $app"
Write-Host "Start it from the Start menu ('$AppName'); a tray icon opens it in your browser."
