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

  Shortcuts: setup adds a Start menu entry (-NoShortcut skips it) and offers a
  desktop shortcut (-DesktopShortcut yes|no|ask; the default asks, and skips it
  when nothing can be asked).

  llama.cpp server: Agent Zero can run its own llama-server.exe instead of
  needing LM Studio. -Llama chooses the build to download during setup
  (cuda, vulkan, rocm, cpu, auto = detect, none = skip; the default asks). The
  download is the official build from github.com/ggml-org/llama.cpp and is
  installed only when its SHA-256 matches the one GitHub publishes. Models
  are never included: you add a .gguf file yourself.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -Version v1.4
  powershell -ExecutionPolicy Bypass -File install.ps1 -Llama cuda     (no questions asked)
#>
param(
    [string]$Version = "",
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "Programs\AgentZeroWindows"),
    [ValidateSet("ask", "auto", "cuda", "vulkan", "rocm", "cpu", "none")][string]$Llama = "ask",
    [switch]$NoShortcut,
    [ValidateSet("ask", "yes", "no")][string]$DesktopShortcut = "ask",
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
# A private pip cache inside the install: the shared per-user cache can hold
# files this account may not read (left by an earlier run as another user or
# as administrator), which made pip fail with "Permission denied".
$env:PIP_CACHE_DIR = Join-Path $app ".pip-cache"
& $venvPython -m pip install --disable-pip-version-check --quiet --upgrade pip
& $venvPython -m pip install --disable-pip-version-check --quiet -r $reqs
if ($LASTEXITCODE -ne 0) {
    Fail "Package installation failed. See the messages above. Running setup again continues where it stopped."
}
Remove-Item -Recurse -Force $env:PIP_CACHE_DIR -ErrorAction SilentlyContinue

# --- llama.cpp server (optional) ------------------------------------------------------
function Install-LlamaServer($choice) {
    $script = @'
import sys
sys.path.insert(0, ".")
from plugins._llama_server.helpers import download
variant = sys.argv[1]
if variant == "auto":
    variant = download.suggested_variant()
print("Downloading the llama.cpp server (" + variant + " build)...")
record = download.download(variant)
print("Installed llama.cpp release " + record["tag"] + " (" + record["variant"] + ")")
from helpers import plugins
plugins.toggle_plugin("_llama_server", True)
print("The llama.cpp server plugin is on: add a .gguf model in Settings > Agent > llama.cpp server.")
'@
    $tmp = Join-Path $env:TEMP ("a0-llama-" + [guid]::NewGuid().ToString("N") + ".py")
    Set-Content -Path $tmp -Value $script -Encoding UTF8
    Push-Location $app
    try {
        & $venvPython $tmp $choice
        if ($LASTEXITCODE -ne 0) { Write-Host "The llama.cpp server could not be installed (see above). Everything else is installed; you can retry in Settings > Agent > llama.cpp server." -ForegroundColor Yellow }
    } finally { Pop-Location; Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
}

$llamaChoice = $Llama
if ($llamaChoice -eq "ask") {
    if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) {
        $llamaChoice = "none"
    } else {
        $detected = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { "an NVIDIA GPU was found, so Automatic installs the CUDA build" } else { "no NVIDIA GPU was found, so Automatic installs the CPU build" }
        Write-Host ""
        Write-Host "Agent Zero can run its own llama.cpp server, so you do not need LM Studio." -ForegroundColor Cyan
        Write-Host "It downloads the official llama-server.exe, verified before it is installed."
        Write-Host "You add a .gguf model yourself afterwards (models are never included)."
        Write-Host ""
        Write-Host "  [A] Automatic    NVIDIA CUDA if an NVIDIA GPU is found, otherwise CPU"
        Write-Host "  [C] NVIDIA CUDA  fastest on NVIDIA cards                   (about 630 MB)"
        Write-Host "  [V] Vulkan       AMD, Intel or NVIDIA GPUs                 (about 30 MB)"
        Write-Host "  [R] AMD ROCm     supported AMD cards with AMD's runtime    (about 250 MB)"
        Write-Host "  [P] CPU only     no GPU; slow for large models             (about 20 MB)"
        Write-Host "  [S] Skip         set it up later in Settings"
        Write-Host ""
        Write-Host "On this PC $detected." -ForegroundColor Yellow
        $answer = (Read-Host "Download it now? [A/C/V/R/P/S] (default S)").Trim().ToLower()
        $llamaChoice = switch ($answer) { "a" { "auto" } "c" { "cuda" } "v" { "vulkan" } "r" { "rocm" } "p" { "cpu" } default { "none" } }
    }
}
if ($llamaChoice -ne "none") {
    Step "Installing the llama.cpp server ($llamaChoice)"
    Install-LlamaServer $llamaChoice
}

# --- Start menu and Apps entry ----------------------------------------------------
$pythonw = Join-Path $app ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $app "installer\tray_launcher.pyw"
function New-AppShortcut($folder) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut((Join-Path $folder "$AppName.lnk"))
    $link.TargetPath = $pythonw
    $link.Arguments = "`"$launcher`""
    $link.WorkingDirectory = $app
    $icon = Join-Path $app "installer\agent-zero.ico"
    if (Test-Path $icon) { $link.IconLocation = $icon }
    $link.Description = $AppName
    $link.Save()
}

if (-not $NoShortcut) {
    Step "Adding the Start menu entry"
    New-AppShortcut (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")

    $desktopChoice = $DesktopShortcut
    if ($desktopChoice -eq "ask") {
        if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) {
            $desktopChoice = "no"
        } else {
            Write-Host ""
            $reply = (Read-Host "Add a shortcut to your desktop too? [Y/n]").Trim().ToLower()
            $desktopChoice = if ($reply -in @("", "y", "yes")) { "yes" } else { "no" }
        }
    }
    if ($desktopChoice -eq "yes") {
        Step "Adding the desktop shortcut"
        New-AppShortcut ([Environment]::GetFolderPath("Desktop"))
    }
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
