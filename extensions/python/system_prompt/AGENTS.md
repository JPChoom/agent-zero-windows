# System Prompt Extensions DOX

## Purpose

- Own construction of core system prompt sections.

## Ownership

- Ordered Python files own main, tools, MCP, secrets, skills, and project prompt sections.
- Active project instruction bodies are moved into prompt protocol; the system prompt keeps project metadata and stable project rules.

## Local Contracts

- `_11_tools_prompt.py` looks up the prompt folders once per build and reads each tool file with `files.read_prompt_file` on that list (`_read_tool_prompt`), with the same result as `agent.read_prompt`; keep it that way rather than calling `agent.read_prompt` per file (the per-file folder lookup was most of the 1-2 s build on a live install).
- Preserve ordering where sections depend on earlier context.
- Keep secret-related prompt sections masked and scoped.
- Prompt additions must be bounded and compatible with tool-call contracts.

## Work Guidance

- Coordinate broad system prompt changes with profiles, skills, tools, plugins, and prompt tests.

## Verification

- Inspect rendered system prompts or run prompt-construction tests after changes.

## Child DOX Index

No child DOX files.
