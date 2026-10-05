param(
    [string]$Source = (Split-Path -Parent $PSScriptRoot),  # repo root
    [string]$Destination = "$env:USERPROFILE\Desktop\a0-safe-source.zip"
)
$ErrorActionPreference = "Stop"
$staging = Join-Path $env:TEMP ("a0-export-" + [guid]::NewGuid())
$exclude = @(
    ".venv", "logs", "tmp", "__pycache__", "usr\chats", "usr\memory",
    "usr\scheduler", "usr\.time_travel", "usr\.env", "usr\secrets.env"
)
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    $robocopyArgs = @($Source, (Join-Path $staging "a0"), "/E", "/R:1", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS")
    foreach ($item in $exclude) { $robocopyArgs += @("/XD", (Join-Path $Source $item)) }
    & robocopy @robocopyArgs | Out-Null
    Get-ChildItem $staging -Recurse -Force -Include *.pyc | Remove-Item -Force
    Compress-Archive -Path (Join-Path $staging "a0") -DestinationPath $Destination -Force
    Write-Host "Created safe source archive: $Destination"
} finally { Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue }
