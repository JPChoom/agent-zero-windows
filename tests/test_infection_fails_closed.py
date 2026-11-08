"""The safety check fails closed: an action nobody checked does not run.

Found 2026-11-06 while planning a Utility model on another PC. Four paths let
a tool through unchecked: the model call failing (`except Exception: return`),
any other error in gate() ("non-fatal"), a reply with no verdict counting as
"ok", and a stop during the check being swallowed. Now a failed check retries
on the Main model, then a person decides; no answer means blocked.
"""

import asyncio

import pytest

from helpers.errors import HandledException
from plugins._infection_check.helpers import checker as C
from plugins._safety_policy.helpers import approval_registry


class _LogItem:
    def __init__(self):
        self.kvps = {}

    def update(self, **kw):
        self.kvps.update(kw)


class _Log:
    def __init__(self):
        self.logs = []

    def log(self, **kw):
        item = _LogItem()
        item.kvps.update(kw.get("kvps", {}))
        item.type = kw.get("type")
        item.content = kw.get("content")
        item.heading = kw.get("heading")
        self.logs.append(item)
        return item

    def set_progress(self, *a, **k):
        pass


class _Context:
    id = "ctx"

    def __init__(self):
        self.log = _Log()
        self.data = {}

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value


class _History:
    def __init__(self):
        self.current = type("T", (), {"messages": []})()

    def output(self):
        return []

    def add_message(self, ai, content, id=""):
        self.current.messages.append(content)


class _Model:
    """A model that answers from a script: text, or an exception to raise."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0
        self.kwargs = {}

    async def unified_call(self, messages=None, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0) if self.replies else ""
        if isinstance(reply, BaseException):
            raise reply
        return reply, ""


class _Agent:
    agent_name = "A0"
    number = 0

    def __init__(self, utility, main):
        self.context = _Context()
        self.history = _History()
        self.data = {}
        self.utility, self.main = utility, main

    def get_utility_model(self):
        return self.utility

    def get_chat_model(self):
        return self.main

    def get_data(self, key):
        return self.data.get(key)

    def set_data(self, key, value):
        self.data[key] = value


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    from helpers import notification

    sent = []
    monkeypatch.setattr(notification.NotificationManager, "send_notification",
                        staticmethod(lambda **kw: sent.append(kw)))
    monkeypatch.setattr(C.denials, "describe", lambda agent: "")
    monkeypatch.setattr(C.InfectionChecker, "_schedule_queue_resume", staticmethod(lambda agent: None))
    return sent


def _checker(**cfg):
    base = {"prompt": "p", "clarification_timeout_seconds": 0.3, "history_size": 0}
    base.update(cfg)
    ch = C.InfectionChecker(config=base, iteration=0)
    ch.reasoning_log = "I will run the tests."
    return ch


async def _gate(ch, agent):
    await ch.gate(agent, tool_name="code_execution_tool", tool_args={"code": "pytest"})


def _pending(agent):
    for item in reversed(agent.context.log.logs):
        if item.type == "infection_check_clarification_request" and not item.kvps.get("resolved"):
            return item
    return None


async def _answer(agent, approved):
    for _ in range(400):
        item = _pending(agent)
        if item:
            approval_registry.resolve(item.kvps["approval_id"], approved)
            return item
        await asyncio.sleep(0.005)
    raise AssertionError("nobody was asked")


def _passed(agent):
    return bool(agent.get_data(C.DATA_KEY_PASSED))


# -- a verdict is required ------------------------------------------------------------

@pytest.mark.parametrize("reply", ["", "   ", "I think this looks fine.", "<ok"])
def test_no_verdict_is_never_ok(reply):
    assert C.parse_result(reply)[0] == C.NO_VERDICT


def test_real_verdicts_still_read_the_same():
    assert C.parse_result("reasoning <ok/>")[0] == "ok"
    assert C.parse_result("<terminate/>")[0] == "terminate"
    assert C.parse_result("<clarify>why?</clarify>") == ("clarify", "why?")
    assert C.parse_result("<ok/> no wait <terminate/>")[0] == "terminate"  # the last one counts


# -- the Main model takes over ----------------------------------------------------------

@pytest.mark.parametrize("failure", [ConnectionError("no route to host"), TimeoutError("stalled"), ""])
def test_a_failed_check_is_retried_on_the_main_model(failure):
    agent = _Agent(_Model(failure), _Model("<ok/>"))
    asyncio.run(_gate(_checker(), agent))
    assert _passed(agent) and agent.main.calls == 1 and _pending(agent) is None


@pytest.mark.parametrize("verdict,passes", [("<ok/>", True), ("<terminate/>", False)])
def test_a_tool_call_with_no_streamed_text_is_still_judged(verdict, passes):
    """A native function call can arrive without any streamed reasoning or
    response; the check used to skip it and let the tool run unchecked."""
    agent = _Agent(_Model(verdict), _Model(verdict))
    checker = _checker()
    checker.reasoning_log = ""
    checker.response_log = ""
    if passes:
        asyncio.run(_gate(checker, agent))
        assert _passed(agent)
    else:
        with pytest.raises(HandledException):
            asyncio.run(_gate(checker, agent))
        assert not _passed(agent)
    assert agent.utility.calls + agent.main.calls == 1


def test_the_main_models_verdict_counts_when_it_blocks():
    agent = _Agent(_Model(ConnectionError("down")), _Model("<terminate/>"))
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(), agent))
    assert not _passed(agent)


def test_the_main_model_judges_without_thinking(monkeypatch):
    from plugins._model_config.helpers import thinking

    applied = []
    monkeypatch.setattr(thinking, "apply", lambda model, provider: applied.append(model) or True)
    agent = _Agent(_Model(ConnectionError("down")), _Model("<ok/>"))
    asyncio.run(_gate(_checker(), agent))
    assert applied == [agent.main]


def test_a_check_set_to_the_main_model_uses_it_without_thinking(monkeypatch):
    from plugins._model_config.helpers import thinking

    applied = []
    monkeypatch.setattr(thinking, "apply", lambda model, provider: applied.append(model) or True)
    agent = _Agent(_Model(), _Model("<ok/>"))
    asyncio.run(_gate(_checker(model="main"), agent))
    assert _passed(agent) and agent.utility.calls == 0 and applied == [agent.main]


# -- no model answered: a person decides ---------------------------------------------------

def _both_down():
    return _Agent(_Model(ConnectionError("utility down")), _Model(ConnectionError("main down")))


def test_when_no_model_answers_the_user_can_allow_it():
    async def run():
        agent = _both_down()
        answer = asyncio.create_task(_answer(agent, True))
        await _gate(_checker(), agent)
        item = await answer
        return agent, item

    agent, item = asyncio.run(run())
    assert _passed(agent)
    assert "could not run" in item.content and "utility down" in item.content and "main down" in item.content


def test_when_no_model_answers_the_user_can_block_it():
    async def run():
        agent = _both_down()
        answer = asyncio.create_task(_answer(agent, False))
        with pytest.raises(HandledException):
            await _gate(_checker(), agent)
        await answer
        return agent

    assert not _passed(asyncio.run(run()))


def test_no_answer_means_blocked():
    agent = _both_down()
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(clarification_timeout_seconds=0.05), agent))
    assert not _passed(agent)


def test_with_nobody_to_ask_it_is_blocked_and_the_agent_cannot_clear_it():
    agent = _both_down()
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(clarify_mode="agent"), agent))
    assert not _passed(agent) and _pending(agent) is None
    assert agent.main.calls == 1  # only as the fallback judge, never asked to explain itself


def test_a_model_that_says_nothing_cannot_pass_the_check():
    agent = _Agent(_Model(""), _Model(""))
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(clarification_timeout_seconds=0.05), agent))
    assert not _passed(agent) and agent.utility.calls == 1 and agent.main.calls == 1


def test_a_blocked_check_is_not_reported_as_a_threat(quiet):
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(clarification_timeout_seconds=0.05), _both_down()))
    assert "could not run" in quiet[-1]["message"] and "Threat" not in quiet[-1]["message"]


def test_a_real_terminate_is_still_reported_as_a_threat(quiet):
    with pytest.raises(HandledException):
        asyncio.run(_gate(_checker(), _Agent(_Model("<terminate/>"), _Model())))
    assert "Threat" in quiet[-1]["message"]


def test_a_failed_background_check_is_not_repeated():
    """No model answered it already: straight to the person, without more calls."""
    async def run():
        ch = _checker()
        agent = _both_down()
        ch._task = asyncio.create_task(ch._run_check(agent, "snapshot"))
        ch._snapshot_covers = lambda *a: True
        await asyncio.sleep(0)
        answer = asyncio.create_task(_answer(agent, True))
        await _gate(ch, agent)
        await answer
        return agent

    agent = asyncio.run(run())
    assert (agent.utility.calls, agent.main.calls) == (1, 1) and _passed(agent)


# -- other ways through ---------------------------------------------------------------------

def test_any_other_error_in_the_check_blocks_the_action():
    ch = _checker()

    async def broken(*a, **k):
        raise ValueError("a bug in the check")

    ch._gate_inner = broken
    with pytest.raises(HandledException):
        asyncio.run(_gate(ch, _Agent(_Model(), _Model())))


def test_stopping_the_agent_during_a_check_stops_it():
    class _Hang(_Model):
        async def unified_call(self, messages=None, **kwargs):
            await asyncio.sleep(30)

    async def run():
        agent = _Agent(_Hang(), _Model("<ok/>"))
        gate = asyncio.create_task(_gate(_checker(), agent))
        await asyncio.sleep(0.05)
        gate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gate
        return agent

    assert not _passed(asyncio.run(run()))


def test_stopping_while_waiting_for_a_background_check_stops_it():
    async def run():
        ch = _checker()
        agent = _Agent(_Model("<ok/>"), _Model("<ok/>"))

        async def hang(a, snapshot):
            await asyncio.sleep(30)

        ch._task = asyncio.create_task(hang(agent, "s"))
        ch._snapshot_covers = lambda *a: True
        gate = asyncio.create_task(_gate(ch, agent))
        await asyncio.sleep(0.05)
        gate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await gate
        return agent

    assert not _passed(asyncio.run(run()))
