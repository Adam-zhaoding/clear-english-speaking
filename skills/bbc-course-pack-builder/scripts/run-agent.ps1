param([ValidateSet('serve','demo-package','status')][string]$Command = 'serve')

Set-Location (Resolve-Path "$PSScriptRoot\../../..")
python -m agent.bbc_course_agent $Command
