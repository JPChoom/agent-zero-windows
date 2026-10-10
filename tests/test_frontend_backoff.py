"""Background calls back off while they fail (security investigation finding F4).

A page that lost access (blocked address, expired session, restart) used to
retry load_webui_extensions on every UI event and keep polling every 3-5 s.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read(*parts: str) -> str:
    return PROJECT_ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_backoff_doubles_up_to_the_cap_and_resets_on_success():
    if not shutil.which("node"):
        pytest.skip("Node.js is required to execute backoff.js.")
    module = (PROJECT_ROOT / "webui" / "js" / "backoff.js").as_uri()
    script = f"""
import {{ createBackoff }} from {module!r};
const assert = (ok, msg) => {{ if (!ok) throw new Error(msg); }};
const b = createBackoff({{ baseMs: 1000, maxMs: 4000 }});
assert(b.ready(0), "fresh backoff is ready");
b.fail(0);    assert(!b.ready(999) && b.ready(1000), "first wait 1s");
b.fail(1000); assert(!b.ready(2999) && b.ready(3000), "second wait 2s");
b.fail(3000); assert(!b.ready(6999) && b.ready(7000), "third wait 4s");
b.fail(7000); assert(!b.ready(10999) && b.ready(11000), "capped at 4s");
assert(b.failures === 4, "counts failures");
b.succeed();  assert(b.ready(11000) && b.failures === 0, "success resets");
"""
    subprocess.run(["node", "--input-type=module", "-e", script], check=True, text=True)


def test_extension_loader_backs_off_both_js_and_html_loads():
    source = read("webui", "js", "extensions.js")
    assert 'import { createBackoff } from "./backoff.js";' in source
    assert source.count("failureBackoff(`js:${extensionPoint}`).ready()") == 1
    assert source.count("failureBackoff(`html:${extensionPoint}`).ready()") == 1
    assert source.count(".fail();") == 2
    assert "loadFailures.clear();" in source


@pytest.mark.parametrize(
    "path",
    [
        ("plugins", "_goal", "webui", "goal-store.js"),
        ("plugins", "_context_usage", "webui", "context-usage-store.js"),
    ],
)
def test_polling_stores_back_off_while_failing(path):
    source = read(*path)
    assert 'import { createBackoff } from "/js/backoff.js";' in source
    assert "pollBackoff.ready()" in source
    assert "pollBackoff.fail()" in source
    assert "pollBackoff.succeed()" in source
