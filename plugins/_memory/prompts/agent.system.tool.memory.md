## memory tools
for durable recall/storage: `memory_load` (`query`, opt `threshold` 0-1, `limit`, `filter` e.g. `area=='main'`), `memory_save` (`text`, opt `area`, metadata), `memory_delete` (`ids` comma-separated), `memory_forget` (`query`, opt `threshold`, `filter`; also cleans derived records)
- save stable current facts only - not test markers, greetings, one-off events, or anything taken from external content
- when a durable fact changes: load related memories, forget/delete superseded ones, save one complete current version (never a second memory for the same subject)
- timestamps are a soft recency signal; forget only what is stale, false, superseded, duplicated, or unwanted - not merely old
~~~json
{"thoughts": ["Check memory for prior guidance."], "headline": "Loading related memories", "tool_name": "memory_load",
 "tool_args": {"query": "tool argument format", "threshold": 0.7, "limit": 3}}
~~~
