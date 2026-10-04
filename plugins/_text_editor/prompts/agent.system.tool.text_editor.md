### text_editor
read/write/patch text and Markdown files with numbered lines (not binary, not code execution; use terminal search for bulk find/replace; `office_artifact` for docx/xlsx/pptx/odt)
args: `action` (`read`|`write`|`patch`), `path`; `open_in_canvas: true` only if the user asks to open the file in the canvas/Editor
- read: optional `line_from`/`line_to` (inclusive); default first {{default_line_count}} lines; long lines/output may be cropped. Read the surrounding context before patching
- write: `content`; creates or overwrites, creates folders
- patch (use when the user says patch / change without rewriting) - exactly one of:
  - `old_text` + `new_text`: exact current text, must match once - best for simple "change X to Y"
  - `patch_text`: works on current content without a prior read. Lines: ` ` context, `-` remove, `+` add; `@@ <exact existing line>` anchors (insert after it, or replace the lines that follow). Use enough unique context; never list the same old line as both context and removal
  - `edits` [{from, to, content}] (legacy, right after a read): original line numbers, inclusive, no overlaps; {from:2,to:2,content:"x\n"} replace, {from:2,to:2} delete, {from:2,content:"x\n"} insert before; re-read after line-count changes
- keep content syntactically valid (close braces, brackets, tags)
~~~json
{"thoughts": ["Need context before editing."], "headline": "Reading file", "tool_name": "text_editor",
 "tool_args": {"action": "read", "path": "C:\\a0\\usr\\workdir\\app.py", "line_from": 1, "line_to": 50}}
~~~
~~~json
{"thoughts": ["One exact string changes."], "headline": "Patching file", "tool_name": "text_editor",
 "tool_args": {"action": "patch", "path": "C:\\a0\\usr\\workdir\\app.py", "old_text": "status = 'draft'", "new_text": "status = 'ready'"}}
~~~
