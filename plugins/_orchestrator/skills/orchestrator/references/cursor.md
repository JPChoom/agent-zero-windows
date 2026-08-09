# Cursor CLI

Use Cursor CLI for headless Cursor Agent tasks. The official binary is
`agent`; running it without `-p` starts the interactive terminal UI, so
always use `agent -p` for delegation.

## Install And Probe

```powershell
Get-Command agent -ErrorAction SilentlyContinue
agent --version
agent status
```

If missing, check Cursor's official docs for the current Windows install
method before running an installer - don't guess at a URL or script.

## Smoke Prompt

```powershell
Set-Location $WORKDIR
agent -p --output-format text "Respond exactly: TERMINAL_AGENT_SMOKE_OK"
```

## Login

For scripts, prefer API-key auth:

```powershell
$env:CURSOR_API_KEY = "..."
```

Do not ask the user to paste the key into chat. Ask them to set
`CURSOR_API_KEY` in the environment, or add it through Settings > External
Services > Secrets Management, or directly to `usr\.env` under the install
root.

For browser login instead, run:

```powershell
$env:NO_OPEN_BROWSER = "1"
agent login
```

Relay the printed URL to the user, wait for confirmation, then retry the
smoke prompt. Use `agent status` to check auth and `agent logout` only when
the user explicitly asks to clear Cursor CLI credentials.

## Real Task

```powershell
Set-Location $WORKDIR
agent -p --force --output-format text "$TASK"
```

Use `--output-format json` when the caller needs structured output, or
`--output-format stream-json --stream-partial-output` when polling progress.
