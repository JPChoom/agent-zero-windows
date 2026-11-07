# Editor Plugin DOX

## Purpose

- Own the native Markdown and plain text editor surface for canvas and floating modal workflows.

## Ownership

- `api/` owns editor session and WebSocket handlers.
- `helpers/` owns editor text session and open-file context helpers.
- `prompts/` owns agent-visible open-file context.
- `webui/` owns editor panel, preview, store, and main surface; `webui/editor-review.js` owns the review of agent changes (CodeMirror merge view from `webui/vendor/codemirror`).
- `extensions/` owns editor hook contributions.

## Local Contracts

- Keep editor session state synchronized across API, WebSocket, and WebUI panel behavior.
- Agent changes to an open file wait for review: `sync_external_file_mutations` (called by the text_editor write/patch hooks) keeps the editor text from before the first unreviewed change in `agent_before`. A clean session takes the agent's version; a session with unsaved text keeps it (`agent_conflict`), and `review_state` reads the agent's version from disk. The store polls `review_state` every 2 s while the panel is mounted; the panel shows the merge view with Accept and Reject on each change, plus Reject all, Accept all and Finish. `review_resolve` saves the chosen text when it differs from the agent's version and ends the review. Changes left undecided at Finish are kept. Ace stays the editor for typing.
- Do not expose unsaved content or local paths beyond intended chat/context surfaces.
- Keep the floating Editor modal on the shared surface modal chrome so the header remains draggable while existing Focus mode continues to work.
- Keep Editor Open wired through the File Browser text picker so users can open one or more Markdown or plain text files with an obvious confirmation action.
- Keep Save As distinct from Rename: Save As writes the current editor text to a chosen `.md` or `.txt` path and retargets the active session without removing the original file.
- Preserve source chat context ids when opening Markdown files from tool-result canvas handoffs.
- Files the user opens from the File Browser (`source: "file-browser"`) follow the File Browser access policy (`helpers/file_access.py`, the stricter remote policy for tunnel requests), not only the document roots; such sessions are marked `policy_checked`, saving re-checks the policy for the current request, and Save As outside the document roots is allowed only where the policy allows. Other opens (no source, WebSocket, agent paths) keep the workdir/project roots.

## Work Guidance

- Coordinate editor preview and session changes with canvas surface registration.

## Verification

- Smoke-test opening, editing, previewing, and reconnecting editor sessions after changes.

## Child DOX Index

No child DOX files.
