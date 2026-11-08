### child_agent
named agent in its own chat: keeps its history between tasks, can work while you continue, can be stopped without stopping you
use for separate longer jobs (test suite, research, review); call_subordinate for quick one-off subtasks
args: `action`, `name`, `message`, optional `profile` (first start only), `wait`, `timeout`
actions: `start`/`message` (give a task; same name = same child), `result` (wait for it), `status`, `stop`, `forget`
`wait: false` lets it work while you continue; it works under your permission mode and capability limits
example:
~~~json
{"thoughts": ["A child can run the slow tests meanwhile."], "headline": "Child agent for tests", "tool_name": "child_agent",
 "tool_args": {"action": "start", "name": "tests", "message": "Run pytest in usr/workdir/app; report failing tests with errors.", "wait": false}}
~~~
