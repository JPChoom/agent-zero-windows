# Memory Plugin DOX

## Purpose

- Own persistent memory, knowledge import, vector indexing, and memory management UI.

## Ownership

- `helpers/memory.py` owns FAISS store loading, embedding metadata, and knowledge preload.
- `helpers/knowledge_import.py` and `helpers/memory_consolidation.py` own import and consolidation behavior.
- `helpers/provenance.py` owns memory provenance (`source`, `trust`, `project`, `chat`, `last_used`); `helpers/maintenance.py` owns the report-only health check behind the dashboard's Health button (`memory_dashboard` action `health_report`).
- `tools/` owns memory save/load/delete/forget and behavior adjustment tools.
- `api/` and `webui/` own memory dashboard and knowledge reindex/import flows.
- `prompts/`, `default_config.yaml`, and `plugin.yaml` own memory prompts, defaults, and metadata.

## Local Contracts

- Keep memory scoped by configured subdirectory/context.
- Preserve embedding metadata needed to rebuild indexes safely.
- `memory_load` accepts numeric `threshold` and `limit` values as native numbers or numeric strings and coerces them before vector search.
- Avoid storing transient action-history noise as durable memory.
- Memory poisoning guard: fragment memorization strips `<untrusted_content>` blocks before the utility model sees history; fragment and solution candidates phrased as instructions to the agent (`helpers/untrusted_content.looks_like_injected_instruction`) are discarded.
- Every new memory is stamped with `provenance.stamp` *after* caller-supplied metadata, so a tool call can't claim its own source or trust: memorizers use `source="conversation"`, `memory_save` `source="agent"`, knowledge import `source="user-file"`/`trust="high"`. Trust is `low` only when the chat history contains `<untrusted_content>` from an external source (`provenance.EXTERNAL_SOURCES` or an MCP `server.tool`); local command output and file reads keep `medium`. Consolidation keeps the lowest trust of merged memories.
- Recall updates `last_used` in place (`provenance.touch`: docstore metadata edit, no re-embedding, persisted at most every 10 minutes) and prefixes low-trust memories with a "verify before relying on it" marker.
- `memory_save` refuses instruction-shaped text, like the automatic memorizers.
- The health report never changes or deletes memories; thresholds are on the store's (1 + cosine) / 2 relevance scale.
- Recall injects at most `memory_recall_memories_max_result` (3) memories and `memory_recall_solutions_max_result` (2) solutions above similarity 0.75, each capped at `RECALL_ENTRY_MAX_CHARS` (1500) with a pointer to `memory_load` for the full entry.

## Work Guidance

- Coordinate tool, prompt, and consolidation changes so saved memories remain useful and bounded.

## Verification

- Smoke-test save, recall, delete, dashboard search/update, and knowledge import/reindex after changes.
- `pytest tests/test_memory_provenance.py` for provenance and the health report.

## Child DOX Index

No child DOX files.
