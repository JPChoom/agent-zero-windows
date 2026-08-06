param(
    [string]$Root
)

$ErrorActionPreference = "Stop"

# Resolve the Agent Zero root robustly:
# 1. Explicit -Root argument
# 2. Parent of this saved script's folder
# 3. Current working directory when pasted interactively
if ([string]::IsNullOrWhiteSpace($Root)) {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $Root = Split-Path -Parent $PSScriptRoot
    }
    else {
        $Root = (Get-Location).Path
    }
}

$Root = [System.IO.Path]::GetFullPath($Root)
$python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    throw "Agent Zero root folder not found: $Root"
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment not found at: $python"
}

$coreFiles = @(
    "tools\search_engine.py",
    "run_ui.py"
)

$optionalFiles = @(
    "usr\plugins\terminal_access\api\execute.py",
    "usr\plugins\terminal_access\tools\terminal_tool.py",
    "usr\plugins\terminal_access\helpers\safe_executor.py"
)

$compileFiles = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in $coreFiles) {
    $fullPath = Join-Path $Root $relativePath

    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        throw "Required Agent Zero file is missing: $fullPath"
    }

    $compileFiles.Add($fullPath)
}

foreach ($relativePath in $optionalFiles) {
    $fullPath = Join-Path $Root $relativePath

    if (Test-Path -LiteralPath $fullPath -PathType Leaf) {
        $compileFiles.Add($fullPath)
    }
    else {
        Write-Warning "Optional disabled Terminal Access file is missing: $fullPath"
        Write-Warning "Agent Zero core validation will continue."
    }
}

Write-Host "Validating Agent Zero at: $Root"
Write-Host "Using Python: $python"

# Compile specifically patched files.
& $python -m py_compile @compileFiles

if ($LASTEXITCODE -ne 0) {
    throw "Python compile validation failed."
}

# Compile the application tree while excluding runtime/generated folders.
Push-Location $Root
try {
    & $python -m compileall -q `
        -x '(^|[\\/])(\.venv|usr[\\/](logs|chats|memory|tmp|workdir)|webui[\\/]vendor|node_modules)([\\/]|$)' `
        .

    if ($LASTEXITCODE -ne 0) {
        throw "Full Python tree compile validation failed."
    }

    # Only run pytest when it is installed.
    & $python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pytest') else 1)"
    $pytestInstalled = ($LASTEXITCODE -eq 0)

    if ($pytestInstalled) {
        Write-Host "pytest found. Running test suite..."
        & $python -m pytest -q

        if ($LASTEXITCODE -ne 0) {
            throw "Test suite failed."
        }
    }
    else {
        Write-Warning "pytest is not installed in this virtual environment."
        Write-Warning "Compile validation passed; automated tests were skipped."
        Write-Warning "Optional install command: C:\a0\.venv\Scripts\python.exe -m pip install pytest"
    }
}
finally {
    Pop-Location
}

Write-Host "Agent Zero validation completed successfully." -ForegroundColor Green
