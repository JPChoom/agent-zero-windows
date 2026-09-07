import re
import json
import time
import uuid
import asyncio
from typing import TYPE_CHECKING

from helpers import plugins
from helpers import history as history_helpers
from helpers.errors import HandledException
from plugins._safety_policy.helpers import approval_registry
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from agent import Agent
    from helpers.log import LogItem

PLUGIN_NAME = "_infection_check"
DATA_KEY = f"_plugin.{PLUGIN_NAME}"
DATA_KEY_PASSED = f"{DATA_KEY}.passed"
DATA_KEY_MONO = f"{DATA_KEY}.mono"

_RE_OK = re.compile(r"<ok\s*/>")
_RE_TERMINATE = re.compile(r"<terminate\s*/>")
_RE_CLARIFY = re.compile(r"<clarify>(.*?)</clarify>", re.DOTALL)


def get_config(agent: "Agent") -> dict:
    return plugins.get_plugin_config(PLUGIN_NAME, agent=agent) or {}


def get_checker(agent: "Agent") -> "InfectionChecker":
    """Get or create a checker for the current iteration.

    A new InfectionChecker is created when:
    - The monologue changes (detected via id(loop_data)).
    - The iteration within the same monologue changes.
    """
    loop = getattr(agent, "loop_data", None)
    iteration = loop.iteration if loop else -1
    mono_id = id(loop) if loop else None

    # Reset passed flag on new monologue
    if agent.get_data(DATA_KEY_MONO) != mono_id:
        agent.set_data(DATA_KEY_MONO, mono_id)
        agent.set_data(DATA_KEY_PASSED, False)
        agent.set_data(DATA_KEY, None)  # discard stale checker from previous monologue

    checker: "InfectionChecker | None" = agent.get_data(DATA_KEY)
    if checker is None or checker.iteration != iteration:
        checker = InfectionChecker(config=get_config(agent), iteration=iteration)
        agent.set_data(DATA_KEY, checker)
        agent.set_data(DATA_KEY_PASSED, False)  # re-check each iteration
    return checker


def parse_result(text: str) -> tuple[str, str]:
    """Find the *last* occurrence of any verdict tag in *text*."""
    pos = -1
    action, detail = "ok", ""
    for m in _RE_OK.finditer(text):
        if m.start() > pos:
            pos, action, detail = m.start(), "ok", ""
    for m in _RE_TERMINATE.finditer(text):
        if m.start() > pos:
            pos, action, detail = m.start(), "terminate", ""
    for m in _RE_CLARIFY.finditer(text):
        if m.start() > pos:
            pos, action, detail = m.start(), "clarify", m.group(1).strip()
    return action, detail


class InfectionChecker:

    def __init__(self, config: dict, iteration: int):
        self.mode: str = config.get("mode", "thoughts")
        self.model_choice: str = config.get("model", "utility")
        self.prompt: str = config.get("prompt", "")
        self.history_size: int = int(config.get("history_size", 10))
        self.max_clarifications: int = int(config.get("max_clarifications", 3))
        # Who answers a <clarify>. "user" puts the question to a human;
        # "agent" is the original behaviour, kept for headless runs where
        # nobody is there to answer and a prompt would only ever time out.
        self.clarify_mode: str = str(config.get("clarify_mode", "user")).lower()
        self.clarification_timeout_seconds: float = float(
            config.get("clarification_timeout_seconds", 300)
        )
        self.iteration = iteration

        # Accumulated text from stream callbacks
        self.reasoning_log = ""
        self.response_log = ""

        # Background analysis task
        self._task: asyncio.Task | None = None
        self._check_msgs: list = []

    # -- collection ----------------------------------------------------------

    def collect_reasoning(self, full_text: str):
        self.reasoning_log = full_text

    def collect_response(self, full_text: str):
        # Stop collecting once background analysis has started
        if self._task is None:
            self.response_log = full_text

    # -- analysis trigger ----------------------------------------------------

    def start_analysis(self, agent: "Agent"):
        """Fire-and-forget background check (called from stream extensions)."""
        if self._task is not None:
            return
        snapshot = self._build_log()
        if not snapshot.strip():
            return
        self._task = asyncio.create_task(self._run_check(agent, snapshot))

    # -- gate (called before every tool execution) ---------------------------

    async def gate(self, agent: "Agent", tool_name: str = "", tool_args: dict | None = None):
        """Block until the safety check passes or terminate the agent."""
        try:
            await self._gate_inner(agent, tool_name, tool_args)
        except HandledException:
            raise
        except Exception as e:
            from helpers.print_style import PrintStyle
            PrintStyle(font_color="red", padding=True).print(
                f"Infection check error (non-fatal): {e}"
            )
            try:
                agent.context.log.set_progress("Infection check: error (non-fatal)")
            except Exception:
                pass

    async def _gate_inner(self, agent: "Agent", tool_name: str, tool_args: dict | None):
        if agent.get_data(DATA_KEY_PASSED):
            return
        if not self.reasoning_log and not self.response_log:
            return

        _log = agent.context.log
        _log.set_progress("Infection check: analyzing...")

        # Attach tool context for _build_log()
        if tool_name:
            self._tool_name = tool_name
            try:
                self._tool_args = dict(tool_args) if tool_args else {}
            except Exception:
                self._tool_args = {}
        else:
            self._tool_name = ""
            self._tool_args = {}

        action, detail, cot = None, "", ""

        # Fast path: reuse result if background task already finished.
        if self._task is not None and self._task.done():
            try:
                action, detail, cot = self._task.result()
                _log.set_progress("Infection check: evaluating result...")
            except Exception:
                pass

        # Slow path: rebuild with full tool context.
        if action is None:
            _log.set_progress("Infection check: analyzing with tool context...")
            if self._task is not None:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
                self._task = None

            snapshot = self._build_log()
            if not snapshot.strip():
                return

            self._task = asyncio.create_task(self._run_check(agent, snapshot))
            try:
                action, detail, cot = await self._task
            except asyncio.CancelledError:
                return
            except Exception:
                return

        if action == "ok":
            _log.set_progress("Infection check: passed")
            agent.set_data(DATA_KEY_PASSED, True)
            return

        if action == "clarify":
            warn = agent.context.log.log(
                type="warning",
                heading="Infection check: requesting clarification",
                content=f"Safety concern:\n{cot}" if cot else "",
            )
            action, detail, cot = await self._clarify_loop(agent, detail, warn)
            if action == "ok":
                warn.update(heading="Infection check: clarification passed")
                agent.set_data(DATA_KEY_PASSED, True)
                return

        # terminate
        self._do_terminate(agent, detail, cot)

    # -- internals -----------------------------------------------------------

    def _build_log(self) -> str:
        parts: list[str] = []
        if self.reasoning_log:
            parts.append(f"## Agent Reasoning\n{self.reasoning_log}")
        if self.response_log:
            parts.append(f"## Agent Response\n{self.response_log}")
        if getattr(self, "_tool_name", ""):
            try:
                args_str = json.dumps(self._tool_args, ensure_ascii=False, default=str, indent=2)
            except Exception:
                args_str = str(getattr(self, "_tool_args", {}))
            parts.append(f"## Tool About to Execute\nTool: {self._tool_name}\nArguments:\n{args_str}")
        return "\n\n".join(parts)

    def _get_model(self, agent: "Agent"):
        if self.model_choice == "main":
            return agent.get_chat_model()
        return agent.get_utility_model()

    async def _run_check(self, agent: "Agent", log_text: str) -> tuple[str, str, str]:
        # Build context from recent history
        hist = agent.history.output()
        if self.history_size > 0:
            hist = hist[-self.history_size :]

        # Filter out previously blocked entries
        filtered: list = []
        for entry in hist:
            content = str(entry.get("content", "")) if isinstance(entry, dict) else ""
            if "[BLOCKED]" in content:
                if filtered:
                    filtered.pop()  # also remove the user message before it
                continue
            filtered.append(entry)

        hist_text = history_helpers.output_text(filtered, ai_label="assistant", human_label="user")
        user_msg = (
            f"## Recent Conversation History\n{hist_text}\n\n"
            f"## Current Agent Output to Analyze\n{log_text}"
        )
        self._check_msgs = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=user_msg),
        ]

        model = self._get_model(agent)
        response, _ = await model.unified_call(
            messages=list(self._check_msgs),
        )
        self._check_msgs.append(AIMessage(content=response))

        action, detail = parse_result(response)
        return action, detail, response

    async def _clarify_loop(
        self, agent: "Agent", clarify_text: str, log_item: "LogItem"
    ) -> tuple[str, str, str]:
        if self.clarify_mode != "agent":
            return await self._clarify_with_user(agent, clarify_text, log_item)
        return await self._clarify_with_agent(agent, clarify_text, log_item)

    async def _clarify_with_user(
        self, agent: "Agent", clarify_text: str, log_item: "LogItem"
    ) -> tuple[str, str, str]:
        """Put the safety model's question to the human and wait for a decision.

        The questions this control produces are addressed to a person -
        "Are you okay with...", "should it add an exception first?" - and
        were previously answered by the main model, which replied in the
        user's voice ("Go ahead and run it") and cleared its own gate.
        Observed live: safety_policy denied Invoke-WebRequest, the agent
        moved the same request into a node script, the check caught the
        workaround, and then the agent authorised itself past it. A control
        that any sufficiently persuasive answer can clear is not a control,
        and the model writing the answer is the same one being gated.

        Fails closed. No answer within the timeout is a denial, because the
        alternative - proceeding when nobody confirmed - is what this
        exists to prevent.
        """
        approval_id = str(uuid.uuid4())
        question = clarify_text or "The safety check needs confirmation before this runs."
        tool_args = ""
        try:
            tool_args = json.dumps(self._tool_args, indent=2, default=str)[:2000]
        except Exception:
            tool_args = str(self._tool_args)[:2000]

        timeout = self.clarification_timeout_seconds
        log_item.update(
            heading="Infection check: waiting for your decision",
            content=(
                f"Safety concern:\n{question}\n\n"
                f"Waiting up to {int(timeout)}s for you to Allow or Block."
            ),
        )
        request_item = None
        try:
            request_item = agent.context.log.log(
                type="infection_check_clarification_request",
                content=question,
                kvps={
                    "approval_id": approval_id,
                    "question": question,
                    "tool_name": self._tool_name or "",
                    "tool_args": tool_args,
                    "resolved": False,
                },
            )
        except Exception:
            pass

        try:
            # register() inside the try, not before it: gate() swallows any
            # exception from here as non-fatal and returns, which would let
            # the gated call proceed. A failure to even set up the decision
            # must block, not pass.
            future = approval_registry.register(approval_id)
            approved = await asyncio.wait_for(future, timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError):
            approval_registry.cleanup(approval_id)
            self._finish_clarification(request_item, outcome="timeout")
            return (
                "terminate",
                f"No answer to the safety question within {int(timeout)}s - treated as blocked.",
                f"Q: {question}\nA: (no response from the user)",
            )
        except Exception as exc:
            # Never let a registry problem become an open gate.
            approval_registry.cleanup(approval_id)
            self._finish_clarification(request_item, outcome="error")
            return (
                "terminate",
                f"Could not obtain a decision on the safety question: {exc}",
                f"Q: {question}",
            )

        self._finish_clarification(
            request_item, outcome="allowed" if approved else "blocked"
        )
        if approved:
            return "ok", "", f"Q: {question}\nA: allowed by the user"
        return (
            "terminate",
            "The user blocked this action at the safety check.",
            f"Q: {question}\nA: blocked by the user",
        )

    @staticmethod
    def _finish_clarification(request_item, outcome: str) -> None:
        if request_item is None:
            return
        try:
            # kwargs merge into kvps; kvps= would replace the whole dict and
            # drop the approval_id the frontend keys off.
            request_item.update(resolved=True, outcome=outcome)
        except Exception:
            pass

    async def _clarify_with_agent(
        self, agent: "Agent", clarify_text: str, log_item: "LogItem"
    ) -> tuple[str, str, str]:
        cot_parts: list[str] = []

        # Throttled log display — avoids per-token stream() and O(n²) masking.
        _buf = ""
        _last_flush = 0.0
        _INTERVAL = 0.25  # seconds between UI pushes

        def _flush():
            nonlocal _last_flush
            log_item.update(content=_buf)
            _last_flush = time.monotonic()

        def _append(text: str):
            nonlocal _buf
            _buf += text
            if time.monotonic() - _last_flush >= _INTERVAL:
                _flush()

        for i in range(self.max_clarifications):
            log_item.update(
                heading=f"Infection check: clarification {i + 1}/{self.max_clarifications}",
            )
            _buf = f"Safety model question:\n{clarify_text}\n\nAgent response:\n"
            _flush()

            # Clone conversation and ask the agent to explain
            chat_msgs = agent.history.output_langchain()
            chat_msgs.append(HumanMessage(content=clarify_text))

            async def _agent_cb(chunk: str, full: str):
                if chunk:
                    _append(chunk)

            agent_resp, _ = await agent.get_chat_model().unified_call(
                messages=chat_msgs,
                response_callback=_agent_cb,
            )
            cot_parts.append(f"Q: {clarify_text}\nA: {agent_resp}")
            _append("\n\nSafety model verdict:\n")
            _flush()

            # Feed agent's response back to the check model
            self._check_msgs.append(
                HumanMessage(
                    content=(
                        f"The agent responded:\n\n{agent_resp}\n\n"
                        "Re-evaluate and provide your verdict."
                    )
                )
            )

            async def _check_cb(chunk: str, full: str):
                if chunk:
                    _append(chunk)

            check_resp, _ = await self._get_model(agent).unified_call(
                messages=list(self._check_msgs),
                response_callback=_check_cb,
            )
            self._check_msgs.append(AIMessage(content=check_resp))
            cot_parts.append(f"Safety: {check_resp}")
            _flush()

            action, detail = parse_result(check_resp)
            if action != "clarify":
                return action, detail, "\n\n".join(cot_parts)
            clarify_text = detail

        return "terminate", "Max clarifications exceeded.", "\n\n".join(cot_parts)

    def _do_terminate(self, agent: "Agent", detail: str, cot: str):
        import uuid as _uuid
        content = cot or detail or "Malicious behavior detected."
        msg_id = str(_uuid.uuid4())
        agent.context.log.log(
            type="warning",
            heading="Infection check: TERMINATED",
            content=content,
            id=msg_id,
        )

        # Replace last AI message with a blocked marker
        try:
            msgs = agent.history.current.messages
            if msgs and msgs[-1].ai:
                msgs.pop()
            agent.history.add_message(
                ai=True, content="[BLOCKED] Response terminated by security policy.",
                id=msg_id,
            )
        except Exception:
            pass

        # Desktop notification
        from helpers.notification import (
            NotificationManager,
            NotificationType,
            NotificationPriority,
        )

        NotificationManager.send_notification(
            type=NotificationType.ERROR,
            priority=NotificationPriority.HIGH,
            title="Infection Check",
            message="Threat detected — agent execution terminated.",
            detail=detail or "Malicious behavior detected.",
            display_time=8,
        )

        # process_chain_end won't fire after HandledException,
        # so schedule queue resumption before raising.
        self._schedule_queue_resume(agent)

        raise HandledException(
            Exception("Infection check terminated: " + (detail or "threat detected"))
        )

    @staticmethod
    def _schedule_queue_resume(agent: "Agent"):
        from helpers import message_queue as mq

        if agent.number != 0:
            return
        context = agent.context
        if not mq.has_queue(context):
            return

        async def _resume():
            total_wait = 0.0
            while context.is_running() and total_wait < 60:
                await asyncio.sleep(0.1)
                total_wait += 0.1
            if not context.is_running():
                mq.send_next(context)

        asyncio.create_task(_resume())
