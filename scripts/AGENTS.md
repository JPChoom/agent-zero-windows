# Scripts DOX

## Purpose

- Own maintainer and automation scripts that live outside GitHub workflow directories.
- Keep scripts deterministic, documented by nearby callers, and safe to run in clean checkouts.

## Ownership

- `clean_generated_files.ps1`, `export_safe_source.ps1` and `verify_install.ps1` are Windows maintenance scripts; they default to the repo root (`Split-Path -Parent $PSScriptRoot`), never a fixed install path.
- Additional repository maintenance scripts belong here when they are not runtime application code.

## Local Contracts

- Do not commit secrets, generated credentials, private release notes, or local machine paths.
- Scripts used by CI must have stable inputs and fail with actionable errors.
- Keep script behavior synchronized with callers and tests.

## Work Guidance

- Prefer standard library Python or simple shell-compatible assets unless a dependency already exists for the script's runtime.
- Keep prompts and automation inputs concise and version-controlled.
- Update callers when renaming or moving scripts.

## Verification

- Run targeted tests for any automation script with coverage.

## Child DOX Index

No child DOX files.
