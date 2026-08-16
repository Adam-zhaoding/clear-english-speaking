param(
  [switch]$NoBundle
)

$ErrorActionPreference = 'Stop'
$project = if (Test-Path 'D:\ClearEnglish') { 'D:\ClearEnglish' } else { Resolve-Path (Join-Path $PSScriptRoot '..') }
Set-Location $project
$gnuTools = Join-Path $env:LOCALAPPDATA 'ClearEnglishBuildTools\w64devkit\bin'
if (Test-Path $gnuTools) {
  $env:Path = "$gnuTools;C:\Users\zhaoding\.cargo\bin;$env:Path"
  $env:RUSTUP_TOOLCHAIN = 'stable-x86_64-pc-windows-gnu'
  $tauriTarget = @('--target', 'x86_64-pc-windows-gnu')
} else {
  $tauriTarget = @()
}

python -m pip install keyring pypdf faster-whisper
pyinstaller --noconfirm --clean --onefile --name bbc-course-agent --paths . --collect-all keyring --collect-all pypdf --collect-all faster_whisper agent\entrypoint.py
New-Item -ItemType Directory -Force 'src-tauri\resources' | Out-Null
Copy-Item -Force 'dist\bbc-course-agent.exe' 'src-tauri\resources\bbc-course-agent.exe'

if ($NoBundle) {
  npm run desktop:build -- --no-bundle @tauriTarget
} else {
  npm run desktop:build -- @tauriTarget
}
