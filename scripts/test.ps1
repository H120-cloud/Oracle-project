# Run the full pytest suite from the project root.
# Usage:  .\scripts\test.ps1                  # all tests
#         .\scripts\test.ps1 -m regression    # one marker
#         .\scripts\test.ps1 tests/unit       # one path

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    python -m pytest @ExtraArgs
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $exitCode
