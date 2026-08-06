# skills_cli.py DOX

## Purpose

- Own the `skills_cli.py` helper module.
- This module provides command-line skill listing, search, validation, and creation helpers.
- Keep this file-level DOX profile synchronized with `skills_cli.py` because this directory is intentionally flat.

## Ownership

- `skills_cli.py` owns the runtime implementation.
- `skills_cli.py.dox.md` owns durable notes about responsibilities, contracts, side effects, and verification for that implementation.
- Classes:
- `Skill` (no explicit base class)
- Top-level functions:
- `get_skills_dirs() -> List[Path]`: Get all skill directories
- `parse_skill_file(skill_path: Path) -> Optional[Skill]`: Parse a SKILL.md file and return a Skill object
- `list_skills() -> List[Skill]`: List all available skills
- `find_skill(name: str) -> Optional[Skill]`: Find a skill by name
- `search_skills(query: str) -> List[Skill]`: Search skills by name, description, or tags
- `validate_skill(skill: Skill) -> List[str]`: Validate a skill and return list of issues
- `create_skill(name: str, description: str=..., author: str=...) -> Path`: Create a new skill from template
- `print_skill_table(skills: List[Skill])`: Print skills in a formatted table
- `main()`

## Runtime Contracts

- Helper modules own reusable framework APIs and must preserve public callers unless all callers, tests, and docs are updated together.
- Update this file whenever public functions, classes, persistence behavior, path/security assumptions, side effects, or cross-module contracts change.
- Observed side-effect areas: filesystem reads, filesystem writes, settings/state persistence, secret handling.
- Imported dependency areas include: `argparse`, `dataclasses`, `datetime`, `helpers`, `os`, `pathlib`, `re`, `sys`, `typing`, `yaml`.

## Key Concepts

- Important called helpers/classes observed in the source: `sys.path.insert`, `field`, `Path`, `get_skills_dirs`, `list_skills`, `query.lower`, `exists`, `custom_dir.mkdir`, `skill_dir.exists`, `skill_dir.mkdir`, `mkdir`, `skill_file.write_text`, `readme.write_text`, `argparse.ArgumentParser`, `parser.add_subparsers`, `subparsers.add_parser`, `list_parser.add_argument`, `create_parser.add_argument`, `show_parser.add_argument`, `validate_parser.add_argument`.
- Keep request/response, tool, or helper semantics documented here at the same time as source changes.

## Work Guidance

- Preserve public helper APIs used by core code and plugins unless every caller is updated.
- Keep path, auth, secret, persistence, network, and subprocess behavior explicit and bounded.
- Prefer adding cohesive helper functions here only when behavior is reused across modules.

## Verification

- Run targeted tests for changed helper behavior; run security regressions for auth, filesystem, WebSocket, tunnel, upload, or secret-handling helpers.
- No direct test reference was found by name search; choose the nearest behavioral test or perform a focused smoke check.

## Child DOX Index

No child DOX files.
