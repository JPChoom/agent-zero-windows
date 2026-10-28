# Message Loop End Extensions DOX

## Purpose

- Own backend behavior that runs after a message loop completes.

## Ownership

- Ordered Python files own history organization and chat persistence at loop end.

## Local Contracts

- `_10_organize_history.py` starts the early history compression (`History.compress(soft=True)`) as a low-priority background task each loop; it must stay summarize-only (never drop records), and a `Preempted` from the model layer ends it quietly (result `None`).
- Preserve history consistency before saving chats.
- Do not skip persistence for successful loops unless the hook contract explicitly permits it.

## Work Guidance

- Coordinate changes with chat serialization, history organization, and WebUI refresh behavior.

## Verification

- Smoke-test sending a message, reloading the chat, and checking persisted history after changes.

## Child DOX Index

No child DOX files.
