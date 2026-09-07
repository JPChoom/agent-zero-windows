"""Structural guards on the infection-check audit prompt.

The prompt is the whole security control - there is no code path that
enforces H1-H4, only the auditor model reading these rules. So a careless
edit silently removes a protection with nothing failing. These pin the
parts that must not drift.

Semantic behaviour is verified separately against a live auditor model;
that needs an inference server, so it is not run here.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import yaml as yaml_helper

CONFIG = PROJECT_ROOT / "plugins" / "_infection_check" / "default_config.yaml"


def _prompt() -> str:
    data = yaml_helper.loads(CONFIG.read_text(encoding="utf-8")) or {}
    return data.get("prompt", "")


def test_transmission_is_still_a_hard_terminate():
    """H1 is the rule that matters: reading a secret is recoverable,
    sending it somewhere is not."""
    prompt = _prompt()
    assert "H1. **Credential transmission**" in prompt
    assert "H1" in prompt.split("STEP 2", 1)[1].split("STEP 3", 1)[0]


def test_the_exfiltration_chain_rule_survives():
    """H3 catches read-then-send even when the first step looks harmless.
    Relaxing H2 leans on H3 still being there."""
    prompt = _prompt()
    assert "H3. **Attack chain with stated intent**" in prompt
    assert "Terminate on the FIRST step" in prompt


def test_credential_stores_outside_the_project_still_terminate():
    prompt = _prompt()
    h2 = prompt.split("H2.", 1)[1].split("H3.", 1)[0]
    for material in ("id_rsa", "keychain", "password manager", "browser profile"):
        assert material.lower() in h2.lower(), material


def test_the_frameworks_own_secrets_are_named():
    """usr/.env holds the Agent Zero auth and root passwords and every API
    key. It sits directly under the same usr/ tree that contains the
    agent's workspace, so the rule has to call out that it is NOT inside
    usr/workdir/ - otherwise the workspace carve-out swallows it."""
    h2 = _prompt().split("H2.", 1)[1].split("**Not H2**", 1)[0]
    assert "usr/.env" in h2
    assert "NOT inside" in h2


def test_reading_a_credential_file_in_the_workspace_is_carved_out():
    """The false positive this rework exists to remove: an agent verifying
    a .env it just wrote was terminated."""
    prompt = _prompt()
    assert "**Not H2**" in prompt
    carve = prompt.split("**Not H2**", 1)[1].split("H3.", 1)[0]
    assert "usr/workdir/" in carve
    # It must point at the rules that still apply, not just permit.
    assert "H1" in carve and "H3" in carve


def test_the_whole_workspace_counts_not_just_the_active_project():
    """Second false positive, from the first attempt at this rule: the
    agent cloned a repo into usr/workdir/ alongside the project it was
    building and was terminated for reading it, because a sibling
    directory read as "outside the project"."""
    carve = _prompt().split("**Not H2**", 1)[1].split("H3.", 1)[0]
    assert "sibling" in carve.lower()
    assert "cloned" in carve.lower()


def test_example_and_template_files_are_not_credentials():
    """.env.example holds placeholders by design and is normally committed
    to a public repo. Terminating on one blocks the ordinary way of
    learning what configuration a project expects."""
    carve = _prompt().split("**Not H2**", 1)[1].split("H3.", 1)[0]
    for marker in (".env.example", ".env.sample", ".env.template"):
        assert marker in carve, marker
    assert "placeholder" in carve.lower()


def test_masked_output_is_not_treated_as_exposure():
    """Variable names without values are not secrets, and the agent
    masking them is the behaviour we want to encourage, not punish."""
    carve = _prompt().split("**Not H2**", 1)[1].split("H3.", 1)[0]
    assert "masked" in carve.lower()


def test_the_verdict_contract_is_intact():
    """checker.parse_result only understands these three tags."""
    prompt = _prompt()
    for tag in ("<ok/>", "<terminate/>", "<clarify>"):
        assert tag in prompt


def test_the_shipped_prompt_parses():
    """A YAML break here disables the whole control at load time."""
    data = yaml_helper.loads(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("prompt")
