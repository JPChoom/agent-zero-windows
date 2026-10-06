### windows_setting
change a few safe per-user Windows settings instead of clicking through Settings
args: `action` ("list", "get" or "set"), optional `setting`, `value`
settings: theme (light/dark), file_extensions, hidden_files (show/hide), taskbar_alignment (left/center), power_plan, wallpaper (image in the work folder)
- `set` reports the previous value and how to undo it; anything not listed: tell the user
