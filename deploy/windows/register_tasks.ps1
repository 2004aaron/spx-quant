# Registers the two StormGlass scans in Windows Task Scheduler (Alpha host, proposal 4.5).
# Times are this PC's local clock, so the PC must be on Pacific time.
# Run once from the repo in PowerShell:  .\deploy\windows\register_tasks.ps1
param(
    [string]$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path,
    [string]$Python = (Get-Command python).Source,
    [string]$ProfilePath = "$env:USERPROFILE\.spx-quant\profile.json",
    [string]$Db = "$env:USERPROFILE\.spx-quant\quant.db"
)

function Add-Job([string]$Name, [string]$At, [string]$Command) {
    $argline = "-m spx_quant --profile `"$ProfilePath`" --db `"$Db`" $Command"
    $action = New-ScheduledTaskAction -Execute $Python -Argument $argline -WorkingDirectory $Repo
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
    # WakeToRun: a sleeping laptop is the main risk to A-KR1. StartWhenAvailable: a missed slot still runs,
    # and the alert says how late it was.
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "registered '$Name' at $At -> python $argline"
}

Add-Job "StormGlass scan 10:30" "10:30" "scan --slot 10:30"
Add-Job "StormGlass scan 13:25" "13:25" "scan --slot 13:25"
Write-Host "Check with: Get-ScheduledTask 'StormGlass*' | Get-ScheduledTaskInfo"
