# Hermes Agent

Use Hermes Agent for quiet headless chat. Skip approvals by default for
non-interactive delegation.

## Install And Probe

```powershell
Get-Command hermes -ErrorAction SilentlyContinue
hermes --version
```

If missing, check the tool's official docs for the current Windows install
method before running an installer - don't guess at a URL or script.

## Smoke Prompt

```powershell
Set-Location $WORKDIR
hermes chat --quiet --source tool -q "Respond exactly: TERMINAL_AGENT_SMOKE_OK" --yolo
```

## Login

If Hermes needs setup, run `hermes setup --portal` when available, relay the
OAuth/browser instructions to the user, wait for confirmation, and retry the
smoke prompt. If it asks for a provider API key, have the user type it into
the CLI prompt or set it as an environment variable outside chat.

## Real Task

Replace the smoke prompt's text with `$TASK`. Add `--model`, `--provider`,
or `--toolsets` only when the user or settings provide them.
