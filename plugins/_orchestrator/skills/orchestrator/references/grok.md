# Grok Build

Use Grok Build for headless xAI coding-agent tasks. Running `grok` with no
arguments starts the interactive TUI, so always use `-p` for delegation.

## Install And Probe

```powershell
Get-Command grok -ErrorAction SilentlyContinue
if (-not $?) { npm install -g @xai-official/grok }
grok --version
```

## Smoke Prompt

```powershell
grok --no-auto-update --cwd $WORKDIR -p "Respond exactly: TERMINAL_AGENT_SMOKE_OK" --output-format json --always-approve --no-alt-screen
```

## Login

Prefer API-key auth for headless automation:

```powershell
$env:XAI_API_KEY = "xai-..."
```

Do not ask the user to paste the key into chat. Ask them to set
`XAI_API_KEY` in the environment, or add it through Settings > External
Services > Secrets Management, or directly to `usr\.env` under the install
root.

For account login instead, run:

```powershell
grok login --device-auth
```

Relay the printed URL and user code to the user, wait for confirmation, then
retry the smoke prompt. Do not run bare `grok`; it opens the full-screen TUI.

## Real Task

```powershell
grok --no-auto-update --cwd $WORKDIR -p "$TASK" --output-format json --always-approve --no-alt-screen
```

Add `-m "$MODEL"` only when the user asks for a specific model. For session
continuation, use `--session-id`, `--resume`, or `--continue` only when the
user asks for it.
