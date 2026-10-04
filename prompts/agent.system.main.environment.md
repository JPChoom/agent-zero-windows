## Environment
You run natively on a Windows 11 host - not Docker, Linux, Kali, WSL, a VM, or a container.
- native shell: Windows PowerShell; Agent Zero root: C:\a0
- Python: C:\a0\.venv\Scripts\python.exe (environment C:\a0\.venv)
- use Windows paths (C:\folder\file.ext) and PowerShell syntax; no Bash or Linux commands (apt, sudo, chmod, grep, sed, awk, cat, touch, mkdir -p, rm) unless the task targets a Linux or remote system
- PowerShell equivalents: Get-ChildItem, Get-Content, Set-Content, Select-String, New-Item, Copy-Item, Move-Item, Remove-Item, Test-Path, Get-Process, Stop-Process
- packages/tools: winget, Chocolatey, NuGet, dotnet, pip (Python above), MSBuild, Git - check a tool is installed before relying on it
- PowerShell vs Python: use PowerShell for simple Windows operations. For complex text transformations, multi-file patches, or anything that gets fragile under PowerShell quoting, write a small standalone .py script and run it with the Python above - never pass multi-line code inline on the command line
