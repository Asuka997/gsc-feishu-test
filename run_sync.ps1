$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location -Path $PSScriptRoot

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir = Join-Path $PSScriptRoot "logs"
$exportDir = Join-Path $PSScriptRoot "exports"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
New-Item -ItemType Directory -Force -Path $exportDir | Out-Null

$logPath = Join-Path $logDir "sync_$timestamp.log"
$outputPath = Join-Path $exportDir "gsc_weekly_latest.json"

python .\sync_gsc_weekly_to_feishu.py --output $outputPath *>&1 |
    Tee-Object -FilePath $logPath

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
