<#
.SYNOPSIS
Removes the scheduled task "filament-kit sync" (run by the uninstaller). Nothing to do when it is gone.
#>
$ErrorActionPreference = 'Stop'

$TaskName = 'filament-kit sync'
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task '$TaskName'."
} else {
    Write-Output "Scheduled task '$TaskName' is not registered."
}
exit 0
