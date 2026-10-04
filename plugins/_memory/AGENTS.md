# Memory Plugin DOX

## Purpose

- Own persistent memory, knowledge import, vector indexing, and memory management UI.

## Ownership

- `helpers/memory.py` owns FAISS store loading, embedding metadata, and knowledge preload.
- `helpers/knowledge_import.py` and `helpers/memory_consolidation.py` own import and consolidation behavior.
- `tools/` owns memory save/load/delete/forget and behavior adjustment tools.
- `api/` and `webui/` own memory dashboard and knowledge reindex/import flows.
- `prompts/`, `default_config.yaml`, and `plugin.yaml` own memory prompts, defaults, and metadata.

## Local Contracts

- Keep memory scoped by configured subdirectory/context.
- Preserve embedding metadata needed to rebuild indexes safely.
- `memory_load` accepts numeric `threshold` and `limit` values as native numbers or numeric strings and coerces them before vector search.
- Avoid storing transient action-history noise as durable memory.
- Memory poisoning guard: fragment memorization strips `<untrusted_content>` blocks before the utility model sees history; fragment and solution candidates phrased as instructions to the agent (`helpers/untrusted_content.looks_like_injected_instruction`) are discarded.
- Recall injects at most `memory_recall_memories_max_result` (3) memories and `memory_recall_solutions_max_result` (2) solutions above similarity 0.75, each capped at `RECALL_ENTRY_MAX_CHARS` (1500) with a pointer to `memory_load` for the full entry.

## Work Guidance

- Coordinate tool, prompt, and consolidation changes so saved memories remain useful and bounded.

## Verification

- Smoke-test save, recall, delete, dashboard search/update, and knowledge import/reindex after changes.

## Child DOX Index

No child DOX files.
