# Message Loop End Extensions DOX

## Purpose

- Own backend behavior that runs after a message loop completes.

## Ownership

- Ordered Python files own history organization and chat persistence at loop end.

## Local Contracts

- `_10_organize_history.py` starts the early history compression (`History.compress(soft=True)`) as a low-priority background task each loop; it must stay summarize-only (never drop records), and a `Preempted` from the model layer ends it quietly (result `None`). It returns at once when `History.wants_soft_compress()` is false, otherwise waits for a gap of `SOFT_IDLE_SETTLE_SECONDS` (started right after a step, the next step's model call interrupted it almost every time), or goes at once when history is over its limit, because a turn is then waiting for it. After a pass that changed history it saves the chat unless a turn is running (that turn's next step saves) or the chat is gone (`_save_if_idle`), because the step's own save ran before the pass finished.
- Preserve history consistency before saving chats.
- Do not skip persistence for successful loops unless the hook contract explicitly permits it.

## Work Guidance

- Coordinate changes with chat serialization, history organization, and WebUI refresh behavior.

## Verification

- Smoke-test sending a message, reloading the chat, and checking persisted history after changes.

## Child DOX Index

No child DOX files.
