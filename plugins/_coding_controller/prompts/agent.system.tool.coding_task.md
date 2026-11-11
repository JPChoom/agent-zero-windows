### coding_task
own git branch and folder (worktree) for a coding task, so changes stay apart until reviewed
args: `action`, `name`; `repo` (git repo folder) for start; `message` for commit; `child` (a child agent's name) to review or merge its worktree
actions: `start` (work only in the returned `path`), `diff`, `commit`, `merge` (fast-forward into the starting branch, then removes the worktree and branch; `keep: true` keeps them), `discard`, `list`
use for real project changes that need review; not for scratch edits
