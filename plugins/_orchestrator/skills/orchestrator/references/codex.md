# Codex CLI

Use Codex for autonomous coding tasks in a repository. Non-interactive runs
need the sandbox/approval bypass flag since there is no interactive terminal
to answer approval prompts.

## Install And Probe

```powershell
Get-Command codex -ErrorAction SilentlyContinue
if (-not $?) { npm install -g @openai/codex }
codex --version
```

## Login

If Codex reports missing auth, run `codex login`, relay the device/browser
instructions to the user, wait for confirmation, and retry the smoke prompt.

## Smoke Prompt

```powershell
Set-Location $WORKDIR
codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "Respond exactly: TERMINAL_AGENT_SMOKE_OK"
```

## Real Task

```powershell
Set-Location $WORKDIR
codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox "$TASK"
```

Add `-m "$MODEL"` only when the user asks for a specific model.
