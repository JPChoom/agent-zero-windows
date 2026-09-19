from abc import abstractmethod
from typing import Any, Awaitable, Type, cast
from helpers import modules, files
from helpers import cache
from typing import TYPE_CHECKING
from functools import wraps
import inspect
import os

from helpers.print_style import PrintStyle

if TYPE_CHECKING:
    from agent import Agent


DEFAULT_EXTENSIONS_FOLDER = "python/extensions"
USER_EXTENSIONS_FOLDER = "usr/extensions"

_EXTENSIONS_CACHE_AREA = "extension_folder_classes(extensions)"
_CLASSES_CACHE_AREA = "extension_classes(extensions)"
# cache.toggle_area(_EXTENSIONS_CACHE_AREA, False)
# cache.toggle_area(_CLASSES_CACHE_AREA, False)


class _Unset:
    pass


_UNSET = _Unset()
_EXTENSIONS_LOG_COUNTS: dict[str, int] = {}


# debug - extensions call counter
def _log_extension_call(name: str):
    try:
        every = int(os.getenv("EXTENSIONS_LOG", "0"))
    except ValueError:
        return

    if every <= 0:
        return

    _EXTENSIONS_LOG_COUNTS[name] = _EXTENSIONS_LOG_COUNTS.get(name, 0) + 1
    _EXTENSIONS_LOG_COUNTS["_total"] = _EXTENSIONS_LOG_COUNTS.get("_total", 0) + 1

    if _EXTENSIONS_LOG_COUNTS["_total"] % every == 0:
        for key, count in _EXTENSIONS_LOG_COUNTS.items():
            print(f"{str(count):<6} {key}")


# decorator to enable implicit extension points in existing functions
def extensible(func):
    """Make a function emit two implicit extension points around its execution.

    The decorator derives two extension point folder paths from the wrapped
    function:

    - ``_functions/<module path>/<qualname path>/start``
    - ``_functions/<module path>/<qualname path>/end``

    Module path segments come from ``func.__module__`` split by ``.``.
    Qualname path segments come from the full nested ``func.__qualname__`` split
    by ``.``, excluding ``<locals>``.

    Example:

    - module ``helpers.something``
    - qualname ``Outer.Inner.__init__``

    becomes:

    - ``_functions/helpers/something/Outer/Inner/__init__/start``
    - ``_functions/helpers/something/Outer/Inner/__init__/end``

    When the wrapped function is called, the decorator builds a mutable ``data``
    payload and passes it to both extension points:

    - ``data["args"]``: positional args (extensions may replace/mutate)
    - ``data["kwargs"]``: keyword args (extensions may replace/mutate)
    - ``data["result"]``: initialized to an internal sentinel; extensions may set
      this to short-circuit the wrapped function
    - ``data["exception"]``: initialized to an internal sentinel; extensions may
      set this to a ``BaseException`` instance to force-raise

    Sync functions call ``call_extensions_sync``. Async functions call
    ``call_extensions_async``.

    Behavior:

    - ``start`` extensions run first and may mutate inputs or set
      ``data["result"]`` / ``data["exception"]``.
    - If ``data["result"]`` is still unset, the decorator calls the wrapped
      function using the possibly modified ``data["args"]`` / ``data["kwargs"]``.
    - ``end`` extensions run last and may rewrite ``data["result"]`` or replace /
      clear ``data["exception"]``.

    Finally, if ``data["exception"]`` contains an exception it is raised;
    otherwise ``data["result"]`` is returned.
    """

    def _get_agent(args, kwargs):
        from agent import Agent

        candidate = kwargs.get("agent")
        if isinstance(candidate, Agent) and bool(getattr(candidate, "__dict__", None)):
            return candidate

        for a in args:
            if isinstance(a, Agent) and bool(getattr(a, "__dict__", None)):
                return a

        return None

    def _prepare_inputs(args, kwargs):
        module_name = getattr(func, "__module__", "")
        qual_name = getattr(func, "__qualname__", "")
        if not module_name or not qual_name:
            return None

        module_parts = [part for part in module_name.split(".") if part]
        qual_parts = [part for part in qual_name.split(".") if part and part != "<locals>"]
        if not module_parts or not qual_parts:
            return None

        base_path = os.path.join("_functions", *module_parts, *qual_parts)
        start_point = os.path.join(base_path, "start")
        end_point = os.path.join(base_path, "end")

        agent = _get_agent(args, kwargs)

        data = {
            "args": args,
            "kwargs": kwargs,
            "result": _UNSET,
            "exception": None,
        }

        return start_point, end_point, agent, data

    def _process_result(data):
        exc = data.get("exception")
        if isinstance(exc, BaseException):
            raise exc

        return data.get("result")

    def _call_original(data):
        call_args = data.get("args")
        call_kwargs = data.get("kwargs")

        if not isinstance(call_args, tuple):
            call_args = (call_args,)
        if not isinstance(call_kwargs, dict):
            call_kwargs = {}

        try:
            data["result"] = func(*call_args, **call_kwargs)
        except Exception as e:
            data["exception"] = e
            return _UNSET

    async def _run_async(*args, **kwargs):
        prepared = _prepare_inputs(args, kwargs)
        if prepared is None:
            return await func(*args, **kwargs)

        start_point, end_point, agent, data = prepared

        # call pre-extensions
        await call_extensions_async(start_point, agent=agent, data=data)

        # call the original if pre-extensions don't return a result
        if (result := _process_result(data)) is _UNSET:
            _call_original(data)
            try:
                data["result"] = await data["result"]
            except Exception as e:
                data["exception"] = e

        # call post-extensions
        await call_extensions_async(end_point, agent=agent, data=data)

        result = _process_result(data)
        return None if result is _UNSET else result

    def _run_sync(*args, **kwargs):
        prepared = _prepare_inputs(args, kwargs)
        if prepared is None:
            return func(*args, **kwargs)

        start_point, end_point, agent, data = prepared

        # call pre-extensions
        call_extensions_sync(start_point, agent=agent, data=data)

        # call the original if pre-extensions don't return a result
        if (result := _process_result(data)) is _UNSET:
            _call_original(data)

        # call post-extensions
        call_extensions_sync(end_point, agent=agent, data=data)

        result = _process_result(data)
        return None if result is _UNSET else result

    if inspect.iscoroutinefunction(func):
        return wraps(func)(_run_async)

    return wraps(func)(_run_sync)


class Extension:
    # Isolated by default: call_extensions_sync/async catch and log this
    # extension's own exception rather than letting it abort every other
    # extension still queued at that call site. Set True on the handful
    # of extensions whose failure means the turn genuinely cannot proceed
    # safely - a safety gate, secret masking, core prompt assembly, or an
    # exception-handler hook itself (catching there would mask the very
    # failure being handled) - see best_effort's docstring for the same
    # list from before isolation was the default.
    FAIL_LOUD: bool = False

    def __init__(self, agent: "Agent|None", **kwargs):
        self.agent: "Agent|None" = agent
        self.kwargs = kwargs

    @abstractmethod
    def execute(self, **kwargs) -> None | Awaitable[None]:
        pass


def best_effort(heading: str):
    """Decorator for an async Extension.execute(): catch any exception,
    log it under a specific, readable heading, and let the turn continue.

    Isolation itself is now the dispatcher's default (see Extension.FAIL_LOUD
    and _log_extension_failure below) - call_extensions_sync/async catch and
    log a failing extension's own exception rather than letting it abort
    every other extension still queued at that call site. This decorator
    remains useful on top of that for extensions that want a specific,
    readable heading (e.g. "History compression stalled") instead of the
    dispatcher's generic one, or that need the exception caught before some
    of their own cleanup code runs. It is a no-op safety net on extensions
    that already isolate by default; it is never needed for the FAIL_LOUD
    ones, since those are exactly the extensions that must not catch.

    Logging the failure is itself best-effort: a broken log sink must not
    turn into a second, more confusing crash than the one being caught.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            try:
                return await func(self, *args, **kwargs)
            except Exception as e:
                agent = getattr(self, "agent", None)
                if agent is None:
                    return
                try:
                    from helpers import errors as errors_helper

                    agent.context.log.log(
                        type="warning",
                        heading=f"{heading} error",
                        content=errors_helper.format_error(e),
                    )
                except Exception:
                    pass

        return wrapper

    return decorator


def _log_extension_failure(
    extension_point: str, cls: Type["Extension"], agent: "Agent|None", exc: Exception
) -> None:
    """Best-effort log of a failing extension's own exception - matches
    best_effort's own logging discipline: a broken log sink must not turn
    into a second, more confusing crash than the one being caught."""
    if agent is None:
        return
    try:
        from helpers import errors as errors_helper

        agent.context.log.log(
            type="warning",
            heading=f"Extension error: {cls.__name__} ({extension_point})",
            content=errors_helper.format_error(exc),
        )
    except Exception:
        pass


async def call_extensions_async(
    extension_point: str, agent: "Agent|None" = None, **kwargs
):
    _log_extension_call(extension_point)

    # fetch classes for this extension point and agent
    classes = _get_extension_classes(extension_point, agent=agent, **kwargs)

    # execute unique extensions
    for cls in classes:
        if cls.FAIL_LOUD:
            result = cls(agent=agent).execute(**kwargs)
            if isinstance(result, Awaitable):
                await result
            continue

        # Isolated by default: one extension's failure must not abort every
        # other extension still queued at this call site. For system_prompt
        # that used to mean every future turn until whatever broke was
        # fixed; for the rest, the current turn.
        try:
            result = cls(agent=agent).execute(**kwargs)
            if isinstance(result, Awaitable):
                await result
        except Exception as e:
            _log_extension_failure(extension_point, cls, agent, e)


def call_extensions_sync(extension_point: str, agent: "Agent|None" = None, **kwargs):
    _log_extension_call(extension_point)

    # fetch classes for this extension point and agent
    classes = _get_extension_classes(extension_point, agent=agent, **kwargs)

    # execute unique extensions
    for cls in classes:
        if cls.FAIL_LOUD:
            result = cls(agent=agent).execute(**kwargs)
            if isinstance(result, Awaitable):
                raise ValueError(
                    f"Extension {cls.__name__} returned awaitable in sync mode"
                )
            continue

        try:
            result = cls(agent=agent).execute(**kwargs)
            if isinstance(result, Awaitable):
                raise ValueError(
                    f"Extension {cls.__name__} returned awaitable in sync mode"
                )
        except Exception as e:
            _log_extension_failure(extension_point, cls, agent, e)


def get_webui_extensions(
    agent: "Agent | None", extension_point: str, filters: list[str] | None = None
):
    from helpers import subagents

    entries: list[str] = []
    effective_filters = filters or ["*"]

    # search for extension folders in all agent's paths
    folders = subagents.get_paths(
        agent,
        "extensions/webui",
        extension_point,
    )

    extensions = []

    for folder in folders:
        for filter in effective_filters:
            pattern = files.get_abs_path(folder, filter)
            extensions.extend(files.find_existing_paths_by_pattern(pattern))

    for extension in extensions:
        rel_path = files.deabsolute_path(extension)
        entries.append(rel_path)

    return entries


def _get_extension_classes(
    extension_point: str, agent: "Agent|None" = None, **kwargs
) -> list[Type[Extension]]:
    from helpers import subagents

    cache_key = cache.determine_cache_key(agent, extension_point)
    cached = cache.get(_CLASSES_CACHE_AREA, cache_key)
    if cached is not None:
        return cached

    # search for extension folders in all agent's paths
    paths = subagents.get_paths(agent, "extensions/python", extension_point)

    all_exts = [cls for path in paths for cls in _get_extensions(path)]

    # merge: first ocurrence of file name is the override
    unique = {}
    for cls in all_exts:
        file = _get_file_from_module(cls.__module__)
        if file not in unique:
            unique[file] = cls
    classes = sorted(
        unique.values(), key=lambda cls: _get_file_from_module(cls.__module__)
    )
    cache.add(_CLASSES_CACHE_AREA, cache_key, classes)
    return classes


def _get_file_from_module(module_name: str) -> str:
    return module_name.split(".")[-1]


def _get_extensions(folder: str):
    folder = files.get_abs_path(folder)
    cached = cache.get(_EXTENSIONS_CACHE_AREA, folder)
    if cached is not None:
        return cached

    if not files.exists(folder):
        return []

    classes = modules.load_classes_from_folder(folder, "*", Extension)
    cache.add(_EXTENSIONS_CACHE_AREA, folder, classes)
    return classes


def register_extensions_watchdogs():
    from helpers import watchdog, projects

    def extensions_changed(items: list[watchdog.WatchItem]):
        cache.clear(_EXTENSIONS_CACHE_AREA)
        cache.clear(_CLASSES_CACHE_AREA)
        PrintStyle.debug("Extensions watchdog triggered:", items)

    # extensions and usr/extensions
    watchdog.add_watchdog(
        id="extensions_base",
        roots=[
            files.get_abs_path(files.EXTENSIONS_DIR),
            files.get_abs_path(files.USER_DIR, files.EXTENSIONS_DIR),
        ],
        handler=extensions_changed,
    )

    # usr/projects/**/extensions
    watchdog.add_watchdog(
        id="extensions_projects",
        roots=[projects.PROJECTS_PARENT_DIR],
        patterns=[f"*/{projects.PROJECT_META_DIR}/**/{files.EXTENSIONS_DIR}/**/*"],
        handler=extensions_changed,
    )

    # agents and usr/agents
    watchdog.add_watchdog(
        id="extensions_agents",
        roots=[
            files.get_abs_path(files.AGENTS_DIR),
            files.get_abs_path(files.USER_DIR, files.AGENTS_DIR),
        ],
        patterns=[f"*/{files.EXTENSIONS_DIR}/**/*"],
        handler=extensions_changed,
    )
