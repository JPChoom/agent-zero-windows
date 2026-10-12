<#
.SYNOPSIS
  Uninstalls Agent Zero for Windows for the current user.

.DESCRIPTION
  Stops Agent Zero if it runs from this folder, removes the Start menu entry,
  the start-at-logon entry (if it points here) and the Settings > Apps entry,
  and deletes the program. Your data (the usr\ folder: chats, memory,
  settings, secrets, models) is KEPT unless you pass -Clean.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File uninstall.ps1 -InstallDir "$env:LOCALAPPDATA\Programs\AgentZeroWindows"
  ... -Clean    (also delete usr\ and everything in it)
#>
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [switch]$Clean,
    [switch]$Yes,
    # Tests point these elsewhere; normal use never sets them.
    [string]$StartMenuDir = (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string]$UninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgentZeroWindows",
    [string]$RunKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
)

$ErrorActionPreference = "Stop"
$AppName = "Agent Zero for Windows"
$app = [System.IO.Path]::GetFullPath($InstallDir)

if (-not (Test-Path (Join-Path $app "run_ui.py"))) {
    Write-Host "Not an Agent Zero folder: $app" -ForegroundColor Red
    exit 1
}
if (-not $Yes) {
    $what = if ($Clean) { "the program AND all your data in usr\" } else { "the program (your data in usr\ is kept)" }
    $answer = Read-Host "Remove $what from $app ? [y/N]"
    if ($answer -notmatch '^(y|yes)$') { exit 0 }
}

# Stop Agent Zero processes started from this folder (server, launcher, llama-server),
# but not Uninstall.exe: it is waiting for this script (it runs a copy of itself
# from a temporary folder because it cannot delete the folder it runs from).
Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) -and
    $_.Name -ne "Uninstall.exe"
} | ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
}

# Shortcuts and registry entries that belong to this install - and only those:
# another copy of Agent Zero on this PC keeps its own.
function Remove-OwnShortcut($folder) {
    $link = Join-Path $folder "$AppName.lnk"
    if (-not (Test-Path -LiteralPath $link)) { return }
    try {
        $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
        if ($shortcut.TargetPath.StartsWith($app, [StringComparison]::OrdinalIgnoreCase) -or
            $shortcut.Arguments.IndexOf($app, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $shortcut.WorkingDirectory.TrimEnd("\").Equals($app.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $link -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}
Remove-OwnShortcut $StartMenuDir
Remove-OwnShortcut $DesktopDir
if (Test-Path $RunKey) {
    $props = Get-ItemProperty -Path $RunKey
    foreach ($p in $props.PSObject.Properties) {
        if ($p.Value -is [string] -and $p.Value.IndexOf($app, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            Remove-ItemProperty -Path $RunKey -Name $p.Name -ErrorAction SilentlyContinue
        }
    }
}
if (Test-Path $UninstallKey) {
    $registered = (Get-ItemProperty -Path $UninstallKey -ErrorAction SilentlyContinue).InstallLocation
    if ($registered -and $registered.TrimEnd("\").Equals($app.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -Path $UninstallKey -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# The program; usr\ is kept unless -Clean.
Get-ChildItem -LiteralPath $app -Force | Where-Object { $Clean -or $_.Name -ne "usr" } | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
}
if ($Clean) {
    Remove-Item -LiteralPath $app -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "$AppName and all its data were removed."
} else {
    Write-Host "$AppName was removed. Your data is still in $(Join-Path $app 'usr')."
    Write-Host "Delete that folder yourself, or reinstall into the same place to keep using it."
}
