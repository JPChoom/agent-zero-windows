# Behavioral prompt includes
"{{name_pattern}}" files in workdir auto-injected into system prompt
create/edit/delete persist across conversations
preference changes, instruction files, project notes, and prompt includes > persist via text_editor before responding
explicit memory requests like "remember this", "what did I ask you to remember", or "forget this" > use memory tools, not promptinclude files, unless the user asks to edit a file
explicit durable behavior, personality, style, greeting, or exact-response rule requests > use behaviour_adjustment, not promptinclude files, unless the user asks to edit a file
never just acknowledge durable project/instruction changes verbally; persist them to file when the user asks for a file/instruction/preference change
use promptinclude files for persistent project context, reference instructions, and user-authored prompt include files
recursive search alphabetical by full path 
{{if includes}}
### includes
!!! obey all rules preferences instructions below

{{includes}}
{{endif}}
