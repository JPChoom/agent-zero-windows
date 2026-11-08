"""Which model runs which job, and what happens when the Utility PC is away."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import model_concurrency, perf
from plugins._infection_check.helpers import checker, shadow
from plugins._model_config.helpers import job_routing, model_config, tool_digest

ROOT = Path(__file__).resolve().parents[1]
DELL = "http://203.0.113.5:1234/v1"
MAIN = "http://127.0.0.1:8090/v1"


class _Model:
    def __init__(self, name, fail=None):
        self.name, self.fail, self.calls = name, fail, 0
        self.marker = name

    async def unified_call(self, *args, **kwargs):
        self.calls += 1
        if self.fail:
            callback = kwargs.get("response_callback")
            if callback and self.fail == "stream":
                await callback("par", "par")
                raise OSError("connection lost")
            raise self.fail
        return self.name, ""


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(job_routing, "_checked", {})


@pytest.fixture
def setup(monkeypatch):
    routing = {"fallback_to_main": True, "jobs": {}, "subordinate_profiles": []}
    state = SimpleNamespace(routing=routing, utility=_Model("utility"), main=_Model("main"), single=False)
    chat = {"provider": "llama_cpp", "name": "big", "api_base": MAIN, "ctx_length": 65536, "ctx_history": 0.7}
    utility = {"provider": "lm_studio", "name": "small", "api_base": DELL, "ctx_length": 32768}
    monkeypatch.setattr(model_config, "get_config", lambda agent=None, **k: {"job_routing": state.routing, "chat_model": chat, "utility_model": utility})
    monkeypatch.setattr(model_config, "_resolve_override", lambda agent=None: None)
    monkeypatch.setattr(model_config, "is_single_model_mode", lambda agent=None: state.single)
    monkeypatch.setattr(model_config, "build_utility_model", lambda agent=None: state.utility)
    monkeypatch.setattr(model_config, "build_main_for_utility", lambda agent=None: state.main)
    return state


def _call(model, **kwargs):
    return asyncio.run(model.unified_call(**kwargs))


def _as_job(caller):
    return perf.CALLER.set(caller)


# -- fallback -----------------------------------------------------------------

def test_utility_runs_while_its_server_answers(setup):
    job_routing._checked[DELL] = (True, 1e12)
    assert _call(job_routing.utility_model_for_call(None))[0] == "utility"
    assert setup.main.calls == 0


def test_a_sleeping_server_sends_the_job_to_main_without_calling_it(setup):
    job_routing._checked[DELL] = (False, 1e12)
    assert _call(job_routing.utility_model_for_call(None))[0] == "main"
    assert setup.utility.calls == 0


def test_a_real_closed_port_counts_as_away():
    assert asyncio.run(job_routing.available("http://127.0.0.1:9/v1")) is False
    assert job_routing.is_marked_down("http://127.0.0.1:9/v1")


def test_a_cloud_provider_with_no_address_is_not_checked():
    assert asyncio.run(job_routing.available(None)) is True


def test_a_connection_failure_moves_the_job_and_marks_the_server(setup):
    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = ConnectionError("gone")
    assert _call(job_routing.utility_model_for_call(None))[0] == "main"
    assert job_routing.is_marked_down(DELL)


def test_one_refused_request_moves_that_job_but_the_server_stays_up(setup):
    class BadRequestError(Exception):
        pass

    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = BadRequestError("prompt over the context")
    assert _call(job_routing.utility_model_for_call(None))[0] == "main"
    assert not job_routing.is_marked_down(DELL)


def test_a_stop_is_not_a_fallback(setup):
    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        _call(job_routing.utility_model_for_call(None))
    assert setup.main.calls == 0


def test_a_preempted_job_is_retried_not_moved(setup):
    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = model_concurrency.Preempted("the turn wants it")
    with pytest.raises(model_concurrency.Preempted):
        _call(job_routing.utility_model_for_call(None))
    assert setup.main.calls == 0


def test_a_half_streamed_answer_is_not_answered_twice(setup):
    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = "stream"

    async def callback(chunk, total):
        pass

    with pytest.raises(OSError):
        _call(job_routing.utility_model_for_call(None), response_callback=callback)
    assert setup.main.calls == 0


def test_the_setting_turns_fallback_off(setup):
    setup.routing["fallback_to_main"] = False
    assert job_routing.utility_model_for_call(None) is setup.utility


@pytest.mark.parametrize("single", [True, False])
def test_no_fallback_when_utility_is_the_main_model(setup, monkeypatch, single):
    setup.single = single
    if not single:
        monkeypatch.setattr(job_routing, "_same_server", lambda agent: True)
    assert job_routing.utility_model_for_call(None) is setup.utility


def test_other_attributes_reach_the_utility_model(setup):
    assert job_routing.utility_model_for_call(None).marker == "utility"


# -- per job ------------------------------------------------------------------

@pytest.mark.parametrize("job,callers", job_routing.JOBS.items())
def test_a_job_set_to_main_runs_on_main(setup, job, callers):
    setup.routing["jobs"] = {job: "main"}
    for caller in callers:
        token = _as_job(caller)
        try:
            assert job_routing.utility_model_for_call(None) is setup.main
        finally:
            perf.CALLER.reset(token)


def test_other_jobs_stay_on_utility(setup):
    setup.routing["jobs"] = {"memorize": "main"}
    token = _as_job("rename_chat")
    try:
        assert job_routing.utility_model_for_call(None) is not setup.main
    finally:
        perf.CALLER.reset(token)


def test_the_settings_list_shows_every_job():
    html = (ROOT / "plugins/_model_config/webui/config.html").read_text(encoding="utf-8")
    shown = re.findall(r"\['(\w+)', '[^']+'\]", html)
    assert shown == list(job_routing.JOBS)


@pytest.mark.parametrize("callers", job_routing.JOBS.values())
def test_every_job_name_is_a_real_tag(callers):
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for folder in ("plugins", "extensions", "helpers")
        for path in (ROOT / folder).rglob("*.py")
    )
    for caller in callers:
        assert f'perf.tagged("{caller}"' in sources


def test_a_digest_never_falls_back_to_main(setup):
    token = _as_job("tool_digest")
    try:
        assert job_routing.utility_model_for_call(None) is setup.utility
    finally:
        perf.CALLER.reset(token)


# -- subordinates -------------------------------------------------------------

def _subordinate(profile="researcher", number=1):
    return SimpleNamespace(number=number, config=SimpleNamespace(profile=profile))


def test_only_listed_subordinates_move(setup):
    setup.routing["subordinate_profiles"] = ["researcher"]
    assert model_config.subordinate_on_utility(_subordinate())
    assert not model_config.subordinate_on_utility(_subordinate("developer"))
    assert not model_config.subordinate_on_utility(_subordinate(number=0))  # never the main agent
    assert not model_config.subordinate_on_utility(None)


def test_nothing_moves_by_default_or_in_single_model_mode(setup):
    assert not model_config.subordinate_on_utility(_subordinate())
    setup.routing["subordinate_profiles"] = ["researcher"]
    setup.single = True
    assert not model_config.subordinate_on_utility(_subordinate())


def test_a_subordinate_gets_the_small_context_and_keeps_main_limits(setup):
    setup.routing["subordinate_profiles"] = ["researcher"]
    slot = model_config.get_chat_model_config(_subordinate())
    assert (slot["name"], slot["api_base"], slot["ctx_length"]) == ("small", DELL, 32768)
    assert slot["ctx_history"] == 0.7 and slot["vision"] is False
    assert slot["kwargs"]["a0_api_mode"] == "chat_completions"
    assert model_config.get_chat_model_config(_subordinate(), routed=False)["name"] == "big"


@pytest.mark.parametrize("caller", ["infection_check", "infection_check_clarify"])
def test_the_safety_check_never_follows_a_subordinate_to_utility(setup, caller):
    setup.routing["subordinate_profiles"] = ["researcher"]
    token = _as_job(caller)
    try:
        assert model_config.get_chat_model_config(_subordinate())["name"] == "big"
    finally:
        perf.CALLER.reset(token)


def test_a_subordinate_returns_to_main_when_the_server_is_away(setup, monkeypatch):
    import importlib

    module = importlib.import_module(
        "plugins._model_config.extensions.python.chat_model_call_before._10_subordinate_route")
    setup.routing["subordinate_profiles"] = ["researcher"]
    job_routing._checked[DELL] = (False, 1e12)
    monkeypatch.setattr(model_config, "build_chat_model", lambda agent, routed=True: "real main" if not routed else "small")
    data = {"model": "small"}
    asyncio.run(module.SubordinateRoute(agent=_subordinate()).execute(call_data=data))
    assert data["model"] == "real main"


# -- tool digest --------------------------------------------------------------

class _Agent:
    def __init__(self, reply="summary of the middle"):
        self.context = SimpleNamespace(id="chat1")
        self.reply = reply
        self.sent = []

    async def call_utility_model(self, system, message, **kwargs):
        self.sent.append(message)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def digest(setup, monkeypatch, tmp_path):
    setup.routing["tool_digest"] = {"enabled": True, "min_chars": 1000, "keep_head_chars": 100, "keep_tail_chars": 100}
    job_routing._checked[DELL] = (True, 1e12)
    monkeypatch.setattr(tool_digest, "_save_full_text", lambda agent, text: (tmp_path / "full.txt").write_text(text, encoding="utf-8") and str(tmp_path / "full.txt"))
    return tmp_path


TEXT = "H" * 100 + "m" * 2000 + "T" * 100


def _shorten(agent, tool="code_execution_tool", text=TEXT):
    return asyncio.run(tool_digest.shorten(agent, tool, text))


def test_the_start_and_end_stay_and_the_full_text_is_saved(digest):
    agent = _Agent()
    result = _shorten(agent)
    assert result.startswith("H" * 100) and result.endswith("T" * 100)
    assert "summary of the middle" in result and str(digest / "full.txt") in result
    assert "m" * 50 not in result
    assert agent.sent == ["m" * 2000]
    assert (digest / "full.txt").read_text(encoding="utf-8") == TEXT


@pytest.mark.parametrize("change", ["off", "short", "tool", "same_model", "away", "error", "empty", "long_summary"])
def test_any_doubt_leaves_the_result_as_it_was(digest, setup, monkeypatch, change):
    agent = _Agent()
    tool, text = "code_execution_tool", TEXT
    if change == "off":
        setup.routing["tool_digest"]["enabled"] = False
    elif change == "short":
        text = "short"
    elif change == "tool":
        tool = "text_editor"  # code is read exactly
    elif change == "same_model":
        setup.single = True
    elif change == "away":
        job_routing._checked[DELL] = (False, 1e12)
    elif change == "error":
        agent.reply = RuntimeError("no")
    elif change == "empty":
        agent.reply = "  "
    elif change == "long_summary":
        agent.reply = "x" * 5000
    assert _shorten(agent, tool, text) == text


def test_off_by_default(setup):
    assert tool_digest.DEFAULTS["enabled"] is False
    defaults = (ROOT / "plugins/_model_config/default_config.yaml").read_text(encoding="utf-8")
    assert "subordinate_profiles: []" in defaults and "enabled: false" in defaults


def test_a_digest_of_outside_text_stays_outside_text():
    """Wrapped by tool name, whatever the text says."""
    from helpers import untrusted_content

    assert not untrusted_content.is_trusted_tool("search_engine")


# -- shadow check -------------------------------------------------------------

@pytest.fixture
def shadow_setup(setup, monkeypatch, tmp_path):
    monkeypatch.setattr(shadow, "_running", False)
    log = tmp_path / "shadow.jsonl"
    monkeypatch.setattr(shadow.files, "get_abs_path", lambda *a, **k: str(log))
    job_routing._checked[DELL] = (True, 1e12)
    setup.log = log
    return setup


def _messages():
    return [SimpleNamespace(content="system"), SimpleNamespace(content="a private command")]


def _shadow_run(verdict_reply, main_verdict="terminate"):
    async def run():
        shadow.start(None, _messages(), main_verdict, checker.parse_result)
        await asyncio.gather(*list(shadow._tasks))

    asyncio.run(run())


def test_a_comparison_is_logged_without_the_text(shadow_setup):
    shadow_setup.utility.name = "<ok/>"
    _shadow_run("<ok/>")
    row = json.loads(shadow_setup.log.read_text(encoding="utf-8"))
    assert (row["main"], row["shadow"]) == ("terminate", "ok")
    assert "private" not in shadow_setup.log.read_text(encoding="utf-8") and len(row["input_sha256"]) == 64


def test_a_failed_shadow_logs_the_error_and_clears(shadow_setup):
    shadow_setup.utility.fail = ConnectionError("gone")
    _shadow_run("")
    assert json.loads(shadow_setup.log.read_text(encoding="utf-8"))["error"] == "ConnectionError"
    assert shadow._running is False


def test_one_shadow_at_a_time(shadow_setup):
    shadow_setup.utility.name = "<ok/>"

    async def run():
        shadow.start(None, _messages(), "ok", checker.parse_result)
        shadow.start(None, _messages(), "ok", checker.parse_result)
        assert len(shadow._tasks) == 1
        await asyncio.gather(*list(shadow._tasks))

    asyncio.run(run())
    assert len(shadow_setup.log.read_text(encoding="utf-8").splitlines()) == 1


def test_no_shadow_when_utility_is_the_main_model(shadow_setup):
    shadow_setup.single = True
    shadow.start(None, _messages(), "ok", checker.parse_result)
    assert shadow._running is False and not shadow._tasks


def test_the_shadow_is_off_by_default():
    assert "shadow_utility: false" in (ROOT / "plugins/_infection_check/default_config.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("enabled,choice,expected", [(True, "main", 1), (False, "main", 0), (True, "utility", 0)])
def test_the_check_starts_a_shadow_only_when_main_judges(setup, monkeypatch, enabled, choice, expected):
    started = []
    monkeypatch.setattr(shadow, "start", lambda agent, messages, verdict, parse: started.append(verdict))
    instance = checker.InfectionChecker(config={"shadow_utility": enabled, "model": choice, "prompt": "rules"}, iteration=0)

    async def ask(model):
        return "ok", "", "<ok/>"

    monkeypatch.setattr(instance, "_ask_model", ask)
    monkeypatch.setattr(instance, "_get_model", lambda agent: None)
    agent = SimpleNamespace(history=SimpleNamespace(output=lambda: []))
    assert asyncio.run(instance._run_check(agent, "tool"))[0] == "ok"
    assert len(started) == expected


def test_a_broken_shadow_cannot_touch_the_verdict(setup, monkeypatch):
    def broken(*args):
        raise RuntimeError("shadow failed")

    monkeypatch.setattr(shadow, "start", broken)
    instance = checker.InfectionChecker(config={"shadow_utility": True, "model": "main", "prompt": "rules"}, iteration=0)

    async def ask(model):
        return "terminate", "", "<terminate/>"

    monkeypatch.setattr(instance, "_ask_model", ask)
    monkeypatch.setattr(instance, "_get_model", lambda agent: None)
    agent = SimpleNamespace(history=SimpleNamespace(output=lambda: []))
    assert asyncio.run(instance._run_check(agent, "tool"))[0] == "terminate"


def test_the_report_counts_what_the_shadow_would_have_missed():
    import importlib.util

    spec = importlib.util.spec_from_file_location("report", ROOT / "tests/manual/safety_shadow_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    summary = report.summarize([
        {"main": "terminate", "shadow": "ok", "seconds": 1},
        {"main": "terminate", "shadow": "clarify", "seconds": 2},
        {"main": "ok", "shadow": "ok", "seconds": 3},
        {"main": "ok", "shadow": "terminate", "seconds": 3},
        {"main": "ok", "shadow": "", "error": "Timeout"},
    ])
    assert (summary["missed"], summary["softer"], summary["agreed"], summary["stricter"], summary["errors"]) == (1, 1, 1, 1, 1)


# -- any model: presets, profiles ---------------------------------------------------

SECOND = "http://203.0.113.9:1234/v1"


@pytest.fixture
def presets(setup, monkeypatch):
    preset = {"name": "Coder", "chat": {"provider": "lm_studio", "name": "coder-14b", "api_base": SECOND, "ctx_length": 16384}}
    monkeypatch.setattr(model_config, "resolve_preset", lambda name, **k: preset if name == "Coder" else None)
    return preset


def test_a_preset_is_a_target(presets):
    slot = model_config.target_slot(None, "preset:Coder")
    assert (slot["name"], slot["api_base"]) == ("coder-14b", SECOND)
    assert model_config.target_slot(None, "preset:Missing") is None
    assert model_config.target_slot(None, "utility")["name"] == "small"
    assert model_config.target_slot(None, "main")["name"] == "big"
    assert model_config.target_slot(None, "nonsense") is None


def test_a_job_can_run_on_a_preset(presets, monkeypatch):
    built = []
    monkeypatch.setattr(model_config, "build_model_for_target", lambda agent, target, utility=False: built.append(target) or _Model("coder"))
    presets  # noqa
    setup_routing = model_config.get_config()["job_routing"]
    setup_routing["jobs"] = {"history_compression": "preset:Coder"}
    job_routing._checked[SECOND] = (True, 1e12)
    token = _as_job("history_compression")
    try:
        assert _call(job_routing.utility_model_for_call(None))[0] == "coder" and built == ["preset:Coder"]
    finally:
        perf.CALLER.reset(token)


def test_profiles_map_to_any_target(presets, setup):
    setup.routing["profile_models"] = "researcher = utility\ndeveloper = preset:Coder\n# a comment\nhacker = main"
    assert model_config.subordinate_target(_subordinate("researcher")) == "utility"
    assert model_config.subordinate_target(_subordinate("developer")) == "preset:Coder"
    assert model_config.subordinate_target(_subordinate("hacker")) == ""  # main is the default anyway
    slot = model_config.get_chat_model_config(_subordinate("developer"))
    assert (slot["name"], slot["ctx_history"]) == ("coder-14b", 0.7)  # its model, Main's limits


def test_the_old_profile_list_still_means_utility(setup):
    setup.routing["subordinate_profiles"] = ["researcher"]
    assert model_config.subordinate_target(_subordinate("researcher")) == "utility"


def test_a_child_agents_own_chat_follows_its_profile_but_the_users_chat_does_not(setup):
    setup.routing["profile_models"] = {"researcher": "utility"}
    child = SimpleNamespace(number=0, config=SimpleNamespace(profile="researcher"), context=SimpleNamespace(data={"child_of": "parent"}))
    own = SimpleNamespace(number=0, config=SimpleNamespace(profile="researcher"), context=SimpleNamespace(data={}))
    assert model_config.subordinate_target(child) == "utility"
    assert model_config.subordinate_target(own) == ""


def test_an_unknown_preset_falls_back_to_main(presets, setup):
    setup.routing["profile_models"] = {"developer": "preset:Missing"}
    assert model_config.subordinate_target(_subordinate("developer")) == ""


# -- error classes, health, history -----------------------------------------------

@pytest.mark.parametrize("exc,kind", [
    (ConnectionError("refused"), "outage"),
    (TimeoutError("slow"), "outage"),
    (type("BadRequestError", (Exception,), {})("This model's maximum context length is 8192 tokens"), "context"),
    (type("BadRequestError", (Exception,), {})("invalid tool schema"), "request"),
    (ValueError("bad json"), "request"),
])
def test_errors_are_classified(exc, kind):
    assert job_routing.classify(exc) == kind


def test_a_refused_request_is_not_resent_to_main(setup):
    job_routing._checked[DELL] = (True, 1e12)
    setup.utility.fail = type("BadRequestError", (Exception,), {})("invalid tool schema")
    with pytest.raises(Exception, match="invalid tool schema"):
        _call(job_routing.utility_model_for_call(None))
    assert setup.main.calls == 0


def test_fallbacks_are_recorded(setup, monkeypatch):
    monkeypatch.setattr(job_routing, "HISTORY", __import__("collections").deque(maxlen=5))
    job_routing._checked[DELL] = (False, 1e12)
    job_routing._reasons[DELL] = "no connection"
    _call(job_routing.utility_model_for_call(None))
    entry = job_routing.HISTORY[-1]
    assert entry["server"] == DELL and entry["reason"] == "no connection" and entry["to"] == "main"


def _serve(status):
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


@pytest.mark.parametrize("status,up", [(200, True), (404, True), (401, True), (503, False)])
def test_a_server_is_ready_only_when_it_answers_for_its_models(status, up):
    server, base = _serve(status)
    try:
        assert asyncio.run(job_routing.available(base)) is up
        if not up:
            assert "not ready" in job_routing._reasons[base]
    finally:
        server.shutdown()


def test_the_settings_show_profiles_presets_and_fallbacks():
    html = (ROOT / "plugins/_model_config/webui/config.html").read_text(encoding="utf-8")
    assert "Model per agent profile" in html and "'preset:' + preset.name" in html and "Recent fallbacks" in html
    assert (ROOT / "plugins/_model_config/api/routing_status.py").is_file()
