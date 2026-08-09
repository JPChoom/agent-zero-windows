# Claude Code

Use Claude Code in print mode. On Windows there is no POSIX root-check to
work around (that upstream Linux/macOS restriction only applies to
`geteuid()==0`) - always use the bypass flags below for non-interactive runs.

## Install And Probe

```powershell
Get-Command claude -ErrorAction SilentlyContinue
if (-not $?) { npm install -g @anthropic-ai/claude-code }
claude --version
claude auth status
```

## Smoke Prompt

```powershell
Set-Location $WORKDIR
claude -p "Respond exactly: TERMINAL_AGENT_SMOKE_OK" --output-format json --permission-mode bypassPermissions --allowedTools Bash,Read,Edit
```

## Login

If Claude Code reports `Not logged in` or asks for `/login`, do not open the
TUI. First ask the user which auth mode to use:

1. Claude subscription: `claude auth login --claudeai`
2. Anthropic Console/API billing: `claude auth login --console`
3. SSO: `claude auth login --sso`
4. API key outside chat: ask the user to open Settings > External Services >
   Secrets Management and enter the key as `ANTHROPIC_API_KEY`, or add it
   directly to `usr\.env` under the install root (e.g. `C:\a0\usr\.env`).

After the user chooses, run only that command and relay its browser/device
instructions. If the user gives an email to prefill, add `--email "<email>"`.
Wait for confirmation, then retry the smoke prompt. Do not start plain
`claude` for login; it opens the first-run TUI (theme/provider menus) and is
not a safe agent-driven login surface. Do not run bare `claude auth login`
when the provider choice is still unknown.

If a previous attempt already opened plain `claude` and the terminal shows
theme/provider menus or no readable login URL, stop. Reset that terminal
session; do not press Enter, do not send `/login`, and do not keep polling
the stuck TUI. Then ask for the auth mode above and run the matching
`claude auth login ...` command in a fresh terminal session.

## Agent Zero Secrets

When using an API key from Agent Zero secrets, load it without printing it.
If the key is stored under a different name (e.g. `API_KEY_ANTHROPIC`), map
it to the variable Claude Code actually reads:

```powershell
$envFile = Join-Path $env:A0_INSTALL_ROOT "usr\.env"  # or the known install path, e.g. C:\a0\usr\.env
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim()) }
}
if (-not $env:ANTHROPIC_API_KEY -and $env:API_KEY_ANTHROPIC) { $env:ANTHROPIC_API_KEY = $env:API_KEY_ANTHROPIC }
```

## Real Task

Replace the smoke prompt's text with `$TASK`.
