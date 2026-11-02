<#
.SYNOPSIS
Registers the scheduled task "filament-kit sync" for the current user: it starts
filament-kit-sync-task.exe (windowed, runs `run --quiet`) every 10 minutes and at logon.

.DESCRIPTION
Run by the installer after the files are copied; no admin rights needed (the task runs as the current
user, with limited rights, only while they are logged on). Running it again replaces the task.
Ported from filament-ops install_sync_task.ps1.
- A run still going when the next one is due is not doubled (-MultipleInstances IgnoreNew).
- A run is stopped after 20 minutes.
- Failed runs are not restarted by Task Scheduler: the sync exits 0 when the server is offline, and
  the next 10-minute run is the retry.
The task holds no secrets: the pairing token stays in the sync's DPAPI-encrypted file.

.PARAMETER ExePath
Full path of filament-kit-sync-task.exe.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath
)
$ErrorActionPreference = 'Stop'

$TaskName = 'filament-kit sync'
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw "filament-kit-sync-task.exe not found at '$ExePath'"
}
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $every, $logon -Settings $settings `
    -Principal $principal -Force `
    -Description 'filament-kit PC sync: uploads Bambu Studio filament presets to the filament-kit server and installs its preset builds while Bambu Studio is closed.' |
    Out-Null
Write-Output "Registered scheduled task '$TaskName' (every 10 minutes and at logon)."
