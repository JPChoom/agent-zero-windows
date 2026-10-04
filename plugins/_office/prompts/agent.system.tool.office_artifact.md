### office_artifact
create/open/read/edit/export Office artifacts in Agent Zero
formats: odt ods odp docx xlsx pptx (defaults: document->odt, spreadsheet->ods, presentation->odp)
actions: create open read edit inspect export version_history restore_version status
args: action kind title format content path file_id operation find replace; UI intent: open_in_canvas open_in_desktop
Office formats only; use `text_editor` for Markdown and plain text files
create/read/edit results save or update artifacts only; they do not open a surface automatically unless the user explicitly asks to open the document UI - only then use action `open`, `open_in_canvas: true` or `open_in_desktop: true` (open surfaces refresh by themselves)
for action `edit`, use operation and put append/prepend/set text in `content` (example: operation `append_text`, content "new line")
after create/edit answer briefly with what changed and the saved path; do not write faux UI action labels like "Open document" or "Download file"
ODF is first-class for LibreOffice (ODT Writer, ODS Calc, ODP Impress); DOCX/XLSX/PPTX are compatibility formats, not defaults - only on explicit request
XLSX charts: edit operation `create_chart` with a `chart` object (line bar column pie area scatter stock ohlc candlestick)
ODS/XLSX: CSV, TSV, Markdown tables or row arrays become real cells
for nontrivial work, load the matching Writer/Calc/Impress skill
