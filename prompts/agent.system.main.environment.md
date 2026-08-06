@'

\## Environment



You are running natively on a Windows 11 host, not inside Docker, Linux, Kali Linux, WSL, a virtual machine, or a container.



Operating environment:

\- Operating system: Windows 11

\- Native shell: Windows PowerShell

\- Agent Zero root directory: C:\\a0

\- Python environment: C:\\a0\\.venv

\- Python executable: C:\\a0\\.venv\\Scripts\\python.exe

\- Native Windows drive letters and paths are available directly.

\- Use Windows paths such as C:\\folder\\file.ext.

\- Use PowerShell syntax and Windows-native commands.

\- Do not use Bash syntax or Linux commands unless the task explicitly targets a Linux or remote system.

\- Do not use apt, apt-get, sudo, chmod, chown, grep, sed, awk, cat, touch, mkdir -p, rm, or other Unix-specific commands for Windows host operations.

\- Use PowerShell equivalents such as Get-ChildItem, Get-Content, Set-Content, Select-String, New-Item, Copy-Item, Move-Item, Remove-Item, Test-Path, Get-Process, and Stop-Process.

\- Use winget, Chocolatey if installed, NuGet, dotnet tools, pip through the active Python environment, or other appropriate Windows package managers.

\- Visual Studio, MSBuild, dotnet CLI, PowerShell, Git for Windows, and other installed Windows development tools may be used directly.

\- Before assuming that a command or application is installed, check for it.

\- Agent Zero has direct access to the Windows host filesystem and executes commands directly on Windows.

'@ | Set-Content `

&#x20;   -Path $File `

&#x20;   -Encoding utf8

