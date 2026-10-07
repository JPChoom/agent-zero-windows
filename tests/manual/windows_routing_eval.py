"""Manual evaluation: does the model route Windows tasks to the right tool?

Not part of the pytest suite (needs a running local model). Builds the real
agent0 system prompt, sends each task as the first user message to an
OpenAI-compatible endpoint (LM Studio by default), and records the first
`tool_name` the model chooses. Runs twice: with the Windows tools and router
("with"), and with those sections removed ("baseline").

    .venv\\Scripts\\python.exe tests\\manual\\windows_routing_eval.py --model qwen3.8-27b-uncensored

Writes a JSON report next to the given --out path. Nothing leaves the PC
when the endpoint is local.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

INFO, SETTING, CU, TERM, EDIT, RESP = "windows_info", "windows_setting", "computer_use", "code_execution_tool", "text_editor", "response"

TASKS: list[tuple[str, set[str]]] = [
    ("Why is my PC slow right now?", {INFO}),
    ("What program is listening on port 5000?", {INFO}),
    ("Did anything crash or log an error on this PC in the last day?", {INFO}),
    ("Is Spotify installed on this computer?", {INFO}),
    ("Switch Windows to dark mode.", {SETTING}),
    ("Show file name extensions in File Explorer.", {SETTING}),
    ("What starts automatically when I sign in?", {INFO}),
    ("How much free space is left on my drives?", {INFO}),
    ("Which Windows version and build is this?", {INFO}),
    ("Is the Print Spooler service running?", {INFO}),
    ("Set my power plan to High performance.", {SETTING}),
    ("List the scheduled tasks that are not from Microsoft.", {INFO}),
    ("What is this PC's local IP address?", {INFO}),
    ("Which apps have windows open right now?", {INFO, CU}),
    ("Open Notepad and type hello in it.", {CU}),
    ("Clone https://github.com/example/demo into the work folder.", {TERM}),
    ("Create a text file called notes.txt containing 'buy milk'.", {EDIT, TERM}),
    ("Is any device showing a driver problem?", {INFO}),
    ("What is in my user PATH environment variable?", {INFO}),
    ("Hide hidden files in Explorer again.", {SETTING}),
    ("Read ProductName from HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion.", {INFO}),
    ("Click the Save button in the Paint window.", {CU, INFO}),  # finding the window first is fine
    ("Turn off the Windows firewall.", {RESP}),
    ("How long has this PC been up since the last reboot?", {INFO}),
]

_TOOL_RE = re.compile(r'"tool_name"\s*:\s*"([^"]+)"')
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_windows_tools(prompt: str) -> str:
    """Baseline: remove the windows_info / windows_setting sections and the router."""
    out = re.sub(r"### windows_info\n.*?(?=\n### |\Z)", "", prompt, flags=re.DOTALL)
    out = re.sub(r"### windows_setting\n.*?(?=\n### |\Z)", "", out, flags=re.DOTALL)
    return out


async def system_prompt() -> str:
    import test_default_prompt_budget as t

    return await t._build_system_text()


def ask(base_url: str, model: str, system: str, user: str, timeout: float) -> tuple[str, float]:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": 1200,
    }).encode()
    req = urllib.request.Request(f"{base_url}/chat/completions", data=body, headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"].get("content") or "", time.time() - start


def first_tool(text: str) -> str:
    """The first tool chosen; for `parallel`, the tool its calls use if they all agree."""
    names = _TOOL_RE.findall(_THINK_RE.sub("", text))
    if not names:
        return "(no tool call)"
    if names[0] == "parallel" and len(set(names[1:])) == 1:
        return names[1]
    return names[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:1234/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default=str(ROOT / "tmp" / "windows_routing_eval.json"))
    ap.add_argument("--timeout", type=float, default=600)
    args = ap.parse_args()

    full = asyncio.run(system_prompt())
    variants = {"with": full, "baseline": strip_windows_tools(full)}
    report: dict = {"model": args.model, "results": {}}
    for name, prompt in variants.items():
        rows, ok = [], 0
        for task, good in TASKS:
            try:
                text, secs = ask(args.base_url, args.model, prompt, task, args.timeout)
                tool = first_tool(text)
            except Exception as exc:
                text, secs, tool = str(exc), 0.0, "(error)"
            hit = tool in good
            ok += hit
            rows.append({"task": task, "tool": tool, "ok": hit, "expected": sorted(good), "seconds": round(secs, 1)})
            print(f"[{name}] {'OK ' if hit else 'MISS'} {tool:22} {secs:6.1f}s  {task}", flush=True)
        report["results"][name] = {"score": f"{ok}/{len(TASKS)}", "rows": rows}
        print(f"== {name}: {ok}/{len(TASKS)}", flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("report:", args.out)


if __name__ == "__main__":
    main()
