<#
.SYNOPSIS
Fresh-clone check: clone to temp, create venv, install, run pytest and
check_setup.py with an empty key (mock mode must pass). Reports
pass/fail per step. Never copies .env (fails if one appears).
.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\fresh_clone_check.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\fresh_clone_check.ps1 -Repo https://github.com/you/HakiScribe-AI.git -Branch main
#>
param(
    [string]$Repo = "",
    [string]$Branch = ""
)
$ErrorActionPreference = "Stop"

$failures = @()

function Step($name, [scriptblock]$body) {
    Write-Host ""
    Write-Host "=== $name ==="
    try {
        & $body
        Write-Host "PASS: $name"
        return $true
    } catch {
        Write-Host "FAIL: $name -- $($_.Exception.Message)"
        $script:failures += $name
        return $false
    }
}

function Run-Checked([string]$exe, [string[]]$cmdArgs, [string]$what) {
    & $exe @cmdArgs
    if ($LASTEXITCODE -ne 0) { throw "$what exited with code $LASTEXITCODE" }
}

$repoUrl = $Repo
if ([string]::IsNullOrWhiteSpace($repoUrl)) {
    $repoUrl = (git remote get-url origin).Trim()
    if ([string]::IsNullOrWhiteSpace($repoUrl)) {
        throw "no -Repo given and no git origin found"
    }
}
$dest = Join-Path ([System.IO.Path]::GetTempPath()) ("hakiscribe-fresh-" + [System.Guid]::NewGuid().ToString("N").Substring(0, 8))
Write-Host "Repo: $repoUrl"
Write-Host "Dest: $dest"

Step "clone" {
    $cloneArgs = @("clone", "--depth", "1")
    if (-not [string]::IsNullOrWhiteSpace($Branch)) {
        $cloneArgs += @("-b", $Branch)
    }
    $cloneArgs += @($repoUrl, $dest)
    Run-Checked "git" $cloneArgs "git clone"
}

if (-not (Test-Path $dest)) { throw "clone folder missing, aborting" }

Step "no .env in clone" {
    if (Test-Path (Join-Path $dest ".env")) {
        throw ".env was copied into the clone"
    }
    Write-Host ".env absent (good)"
}

Push-Location $dest
try {
    Step "venv" {
        Run-Checked "python" @("-m", "venv", ".venv") "venv create"
    }
    $py = Join-Path $dest ".venv\Scripts\python.exe"
    Step "install" {
        Run-Checked $py @("-m", "pip", "install", "-r", "requirements.txt") "pip install"
    }
    Step "pytest" {
        Run-Checked $py @("-m", "pytest", "tests/", "-q") "pytest"
    }
    Step "check_setup mock mode" {
        $env:META_API_KEY = ""
        Run-Checked $py @("scripts/check_setup.py") "check_setup"
    }
} finally {
    Pop-Location
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "FRESH CLONE CHECK: PASS ($dest)"
    exit 0
} else {
    Write-Host "FRESH CLONE CHECK: FAIL [$($failures -join ', ')] ($dest)"
    exit 1
}
