### child_agent
run a named agent in a chat of its own: it keeps its history between tasks, can work while you continue, and can be stopped without stopping you
use it for separate, longer jobs (run the test suite, research a topic, review a change); use call_subordinate for a quick one-off subtask
args: `action`, `name`, `message`, optional `profile`, `wait`, `timeout`
- `action`: `start` or `message` (give it a task; an existing child keeps its history), `result` (wait for its current task), `status` (list your children), `stop`, `forget`
- `name`: short name you choose, for example `tests` or `research`; reuse it to talk to the same child
- `message`: its role, goal and concrete task
- `profile`: optional agent profile, only when it is first started
- `wait`: `true` (default) waits for its answer; `false` lets it work while you continue, then use `result`
- `timeout`: optional seconds to wait for `result`
the child works under your permission mode and capability limits
example:
~~~json
{
  "thoughts": ["The test suite takes a while; a child can run it while I keep fixing the parser."],
  "headline": "Starting a child agent for the tests",
  "tool_name": "child_agent",
  "tool_args": {
    "action": "start",
    "name": "tests",
    "profile": "developer",
    "message": "Run pytest in usr/workdir/app, then report each failing test with its error.",
    "wait": false
  }
}
~~~
