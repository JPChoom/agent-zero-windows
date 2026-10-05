# GitHub Automation DOX

## Purpose

- Own repository automation that runs on GitHub for this Windows-native fork.

## Ownership

- `workflows/tests.yml` runs the pytest suite on `windows-latest` (Python 3.12) for pushes to `main`, pull requests, and manual dispatch.

## Local Contracts

- No publishing, release, Docker, or issue-closing automation: upstream's Docker publish, release-note and stale-issue workflows were removed from this fork.
- Workflows run with read-only `contents` permission and use no secrets. Never commit credentials, tokens, or private data into workflow files or logs.
- Tests must pass on Windows without network credentials or a running model; Linux/Docker-only tests are skipped via `pytest.mark.skipif` in the test files, not removed silently.

## Work Guidance

- Keep the workflow in sync with `requirements.txt` / `requirements.dev.txt` and the Python version in the root `AGENTS.md`.

## Verification

- `python -m pytest -q tests` locally on Windows before pushing; the workflow runs the same command.

## Child DOX Index

No child DOX files.
