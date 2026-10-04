### parallel
run independent tool calls concurrently, or await/cancel background parallel jobs.
Each `tool_calls` item is a normal tool request object using the same `tool_name` and `tool_args` shape as a top-level reply; planning fields like `thoughts` or `headline` are ignored.
Batch all independent calls that are ready now into one `tool_calls` list, even when they use different tools. Do not split by tool type.
Args: `tool_calls`, `job_ids`, `wait` (default true), `action` start|await|collect|cancel, `timeout` (limits only this wait; jobs keep running and can be awaited again by `job_ids`).
- not for one simple call, dependent/ordered steps, shared mutable state, or changes that must happen in the parent context; never nest `parallel`
- Never include `document_query` in `tool_calls`; call it sequentially (too heavy for workers)
- `call_subordinate` inside `parallel` starts an isolated child chat, not a scheduler task
- use `wait: false` only when you will collect results later; collect running/ready jobs listed in extras before final synthesis
~~~json
{"tool_name": "parallel", "tool_args": {"tool_calls": [
  {"tool_name": "call_subordinate", "tool_args": {"message": "Review option A and return key risks.", "reset": true}},
  {"tool_name": "search_engine", "tool_args": {"query": "official API changelog release notes"}}], "wait": true}}
~~~
~~~json
{"tool_name": "parallel", "tool_args": {"action": "await", "job_ids": ["job-id"], "timeout": 300}}
~~~
