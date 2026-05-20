param(
    [string]$TaskName = "GSC Weekly To Feishu",
    [string]$Time = "10:00"
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "run_sync.ps1"
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Sync Google Search Console weekly clicks and impressions to Feishu Bitable." `
    -Force

Write-Host "Registered task '$TaskName' to run daily at $Time."
