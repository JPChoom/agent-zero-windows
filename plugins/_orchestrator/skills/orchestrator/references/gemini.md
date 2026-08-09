# Gemini CLI

Use Gemini CLI for headless Google Gemini coding tasks. Always pass `-p`;
bare `gemini` opens the interactive TUI.

## Install And Probe

Check first:

```powershell
Get-Command gemini -ErrorAction SilentlyContinue
```

If missing, install it as one command and wait for it to complete:

```powershell
npm install -g @google/gemini-cli --no-progress
```

Then probe it:

```powershell
gemini --version
gemini --help
```

## Smoke Prompt

```powershell
Set-Location $WORKDIR
gemini -p "Respond exactly: TERMINAL_AGENT_SMOKE_OK" --output-format json --approval-mode=yolo --skip-trust
```

## Login

Headless mode uses cached Google credentials, a Gemini API key, or Vertex AI
credentials. Do not start bare `gemini` for login; it opens a TUI. For local
browser sign-in, ask the user to run `gemini` in their own terminal, select
**Sign in with Google**, finish in the browser, then retry the smoke prompt.

For automation, prefer `GEMINI_API_KEY`. Ask the user to add it through
Settings > External Services > Secrets Management, or use Agent Zero's
`§§secret(GEMINI_API_KEY)` placeholder so the value is never printed:

```powershell
$env:GEMINI_API_KEY = '§§secret(GEMINI_API_KEY)'
gemini -p "Respond exactly: TERMINAL_AGENT_SMOKE_OK" --output-format json --approval-mode=yolo --skip-trust
```

Vertex AI may instead use `GOOGLE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`,
or cached Application Default Credentials, plus `GOOGLE_CLOUD_PROJECT` and
`GOOGLE_CLOUD_LOCATION`. Never ask the user to paste keys or service-account
JSON into chat.

## Real Task

```powershell
Set-Location $WORKDIR
gemini -p "$TASK" --output-format json --approval-mode=yolo --skip-trust
```

Add `-m "$MODEL"` only when the user asks for a specific model. Use
`--approval-mode=plan` instead of `yolo` when the user explicitly asks for
read-only analysis.
