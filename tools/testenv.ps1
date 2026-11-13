# The test recipe on Windows, where the PC sync's DPAPI and file lock are real: the same idea as tools/testenv.sh.
#
#   powershell -ExecutionPolicy Bypass -File tools\testenv.ps1 [-Only pc-sync,server] [-Workers auto]
#
# The default is pc-sync, which is what Windows proves and what the Windows workflows run. The server runs on Linux; it can be added
# with -Only pc-sync,server, where its golden build needs the Python CI uses (3.12). -Only tests runs the design checks of the
# root tests/ folder (the token files' equality and contrast; on Linux they are in testenv.sh's "other" suite).
#
# It reuses a venv under %LOCALAPPDATA%\filament-kit while server\pyproject.toml, pc-sync\pyproject.toml and the Python version
# stay the same, and the program under test is always this tree's (PYTHONPATH). Exit code non-zero if a suite failed.
param(
    [string[]]$Only = @("pc-sync"),
    [string]$Workers = "auto"
)
$ErrorActionPreference = "Stop"
# powershell -File hands "pc-sync,server" over as one string
$Only = @($Only | ForEach-Object { $_ -split "," })
$root = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $env:LOCALAPPDATA "filament-kit"
New-Item -ItemType Directory -Force $cache | Out-Null

$python = if (Get-Command py -ErrorAction SilentlyContinue) { @("py", "-3") } else { @("python") }
$pyExe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)
$version = & $pyExe @pyArgs --version
$text = (Get-Content -Raw (Join-Path $root "server\pyproject.toml")) + (Get-Content -Raw (Join-Path $root "pc-sync\pyproject.toml")) + $version
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text)) | Select-Object -First 8 | ForEach-Object { $_.ToString("x2") })
$venv = Join-Path $cache "venv-$hash"
$env:PIP_CACHE_DIR = Join-Path $cache "pip"

if (-not (Test-Path (Join-Path $venv ".done"))) {
    Write-Host "==> building the test venv ($venv)"
    if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
    # from a copy: pip leaves build\ in what it builds
    $src = Join-Path $cache ("src-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory $src | Out-Null
    Copy-Item -Recurse (Join-Path $root "server") $src
    Copy-Item -Recurse (Join-Path $root "pc-sync") $src
    & $pyExe @pyArgs -m venv $venv
    & (Join-Path $venv "Scripts\python.exe") -m pip install -q "$src\server[test,web]" "$src\pc-sync[test]"
    $built = $LASTEXITCODE
    Remove-Item -Recurse -Force $src
    if ($built -ne 0) { Write-Error "could not build the test venv" }
    New-Item -ItemType File (Join-Path $venv ".done") | Out-Null
}

# Tests that run a shell script need Git's bash. A plain `bash` on Windows can be WSL's, which can't read these paths.
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $bin = Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) "bin"
    if (Test-Path (Join-Path $bin "bash.exe")) { $env:PATH = "$bin;$env:PATH" }
}
$env:PYTHONPATH = (Join-Path $root "server") + ";" + (Join-Path $root "pc-sync")
$env:PYTHONDONTWRITEBYTECODE = "1"
$py = Join-Path $venv "Scripts\python.exe"
$run = Join-Path $cache ("run-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory $run | Out-Null
$summary = @()
$failed = $false
foreach ($suite in $Only) {
    Write-Host "`n==> $suite"
    $started = Get-Date
    Push-Location (Join-Path $root $suite)
    try {
        & $py -m pytest -q -rfEs -p no:cacheprovider -n $Workers "--basetemp=$run\$suite"
        $rc = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($rc -ne 0) { $failed = $true }
    $word = if ($rc -eq 0) { "ok" } else { "FAIL" }
    $summary += "{0,-5} {1,-8} {2,5}s" -f $word, $suite, [int]((Get-Date) - $started).TotalSeconds
}
Remove-Item -Recurse -Force $run -ErrorAction SilentlyContinue
Write-Host "`n==> summary"
$summary | ForEach-Object { Write-Host $_ }
if ($failed) { exit 1 }
exit 0
