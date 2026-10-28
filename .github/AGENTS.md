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

- The workflow installs `requirements.lock.txt` with `--require-hashes` (exactly what installs and the updater use), then `requirements.dev.txt`. Regenerate the lock (`scripts/make_lock.py`) whenever `requirements.txt` changes, or CI fails.
- Keep tests independent of the developer's machine: no `usr/` contents, no `.venv`, no optional plugin packages (`tmp_path`, `monkeypatch`, `pytest.importorskip`). Before a release, the suite must also pass on a clean checkout (`git archive HEAD` extracted elsewhere) and the last run on `main` must be green.

## Verification

- `python -m pytest -q tests` locally on Windows before pushing; the workflow runs the same command.

## Child DOX Index

No child DOX files.
