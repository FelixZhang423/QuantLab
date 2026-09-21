param(
    [string]$Config = "$PSScriptRoot\runtime.json",
    [int]$RestartDelaySeconds = 30
)

# Keep the bundle independent from the development workspace.
$ErrorActionPreference = "Continue"
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$BundleDir = $PSScriptRoot
$ProjectDir = Split-Path -Parent $BundleDir

Set-Location -LiteralPath $ProjectDir
$configObject = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
$outputDir = Join-Path -Path $BundleDir -ChildPath ([string]$configObject.output_dir)
$logDir = Join-Path -Path $outputDir -ChildPath "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

while ($true) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logPath = Join-Path -Path $logDir -ChildPath "run_$timestamp.log"
    Write-Host "Starting single-factor generation: $timestamp"

    & $Python -m single_factor.cli run --config $Config 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE

    $statePath = Join-Path -Path $outputDir -ChildPath "run_state.json"
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $finished = ([int]$state.accepted_count -ge [int]$state.target_count) -or
            ([int]$state.attempts -ge [int]$state.max_attempts)
        if ($finished) {
            Write-Host "Generation reached its configured stopping condition."
            break
        }
    }

    if ($exitCode -ne 0) {
        Write-Warning "Process exited with code $exitCode; restarting after ${RestartDelaySeconds}s."
    }
    else {
        Write-Host "Process stopped before the stopping condition; restarting after ${RestartDelaySeconds}s."
    }
    Start-Sleep -Seconds $RestartDelaySeconds
}
