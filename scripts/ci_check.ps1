# CI placeholder — runs the full local check suite that any future CI
# system (GitHub Actions, Railway, etc.) should mirror.
#
# Stages (each is gating: a non-zero exit fails the run):
#   1. Syntax-compile every Python file under src/ and tests/.
#   2. Run the full pytest suite.
#
# Add new stages here as the project grows; keep them ordered fast → slow.

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    Write-Host "[ci_check] Stage 1: py_compile" -ForegroundColor Cyan
    $pyFiles = Get-ChildItem -Path "src", "tests" -Recurse -Filter "*.py" -ErrorAction SilentlyContinue
    if (-not $pyFiles) {
        Write-Host "  (no .py files found)" -ForegroundColor Yellow
    }
    else {
        python -m py_compile @($pyFiles.FullName)
        if ($LASTEXITCODE -ne 0) {
            throw "py_compile failed"
        }
    }

    Write-Host "[ci_check] Stage 2: pytest" -ForegroundColor Cyan
    python -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed"
    }

    Write-Host "[ci_check] All stages passed." -ForegroundColor Green
}
finally {
    Pop-Location
}
