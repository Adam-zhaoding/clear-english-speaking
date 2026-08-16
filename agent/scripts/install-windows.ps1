param(
  [Parameter(Mandatory = $true)][string]$AgentExecutable
)

$resolved = (Resolve-Path -LiteralPath $AgentExecutable).Path
$taskName = 'Clear English Speaking BBC Course Agent'
$action = New-ScheduledTaskAction -Execute $resolved -Argument 'serve'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description 'Local-only Clear English Speaking BBC course agent' -Force | Out-Null
Write-Output "Installed $taskName. The agent stays local and applies its editable in-app schedule."
