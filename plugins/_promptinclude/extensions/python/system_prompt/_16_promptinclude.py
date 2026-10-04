import hashlib
import os
import threading

from helpers.extension import Extension
from helpers import debounced, errors, plugins, files, runtime
from helpers import projects
from agent import Agent, LoopData

from plugins._promptinclude.helpers.scanner import scan_promptinclude_files, ScanResult

# scan_promptinclude_files is a real filesystem walk. Outside dev-Docker
# mode (see the branch below), runtime.call_development_function called it
# directly, synchronously, on the event loop, on every single
# prepare_prompt call - blocking the whole server for the walk's duration
# regardless of whether anything had changed.
PROMPTINCLUDE_SCAN_TTL_SECONDS = 10.0

# Prompt includes become trusted system-prompt text, so they are only read
# from places the user controls - never recursively from the whole workdir,
# where cloned repositories, extracted archives and downloads live and could
# plant a matching file:
#   - TRUSTED_DIR (usr/promptincludes/), top level only
#   - the active project's root folder, top level only
TRUSTED_DIR = "usr/promptincludes"
SCAN_DEPTH = 1

_seen_lock = threading.Lock()
_seen_hashes: dict[str, str] | None = None


class PromptInclude(Extension):

    async def execute(
        self,
        system_prompt: list[str] = [],
        loop_data: LoopData = LoopData(),
        **kwargs,
    ):
        if not self.agent:
            return

        # system_prompt runs on every single prepare_prompt call, and this
        # is the one extension on that extension point that does a live
        # filesystem scan. A permission error, a vanished project folder, an
        # RFC/dev-mode connection drop, or a missing prompt template here
        # would otherwise propagate out of call_extensions_async and break
        # prompt assembly for every future turn, not just this one.
        try:
            await self._append_includes(system_prompt)
        except Exception as e:
            err = errors.format_error(e)
            try:
                self.agent.context.log.log(
                    type="warning",
                    heading="Promptinclude extension error",
                    content=err,
                )
            except Exception:
                pass

    async def _append_includes(self, system_prompt: list[str]) -> None:
        config = plugins.get_plugin_config("_promptinclude", agent=self.agent) or {}
        scan_roots = _resolve_scan_roots(self.agent)

        name_pattern = config.get("name_pattern", "*.promptinclude.md")
        max_file_tokens = config.get("max_file_tokens", 2000)
        max_file_count = config.get("max_file_count", 50)
        max_total_tokens = config.get("max_total_tokens", 8000)
        gitignore = config.get("gitignore", "")

        if runtime.is_development() and not runtime.is_windows():
            # RFC dispatch already runs in a separate process, so it does
            # not block this one's event loop - no thread offload needed.
            # This branch is also load-bearing for correctness, not just
            # performance: in this deployment mode the scan has to run
            # against the dev host's view of the filesystem, not this
            # container's, which is the whole reason RFC dispatch exists.
            result = await runtime.call_development_function(
                scan_promptinclude_files,
                scan_roots,
                name_pattern=name_pattern,
                max_depth=SCAN_DEPTH,
                max_file_tokens=max_file_tokens,
                max_file_count=max_file_count,
                max_total_tokens=max_total_tokens,
                gitignore=gitignore,
            )
        else:
            # scan_promptinclude_files has "No agent/tool dependencies"
            # (its own docstring) so it is safe on a worker thread, and
            # debounced since the result rarely changes turn-to-turn.
            cache_key = (
                f"promptinclude:{'|'.join(scan_roots)}:{name_pattern}:{SCAN_DEPTH}:"
                f"{max_file_tokens}:{max_file_count}:{max_total_tokens}:{gitignore}"
            )
            result = await debounced.run_debounced(
                cache_key,
                PROMPTINCLUDE_SCAN_TTL_SECONDS,
                scan_promptinclude_files,
                scan_roots,
                name_pattern=name_pattern,
                max_depth=SCAN_DEPTH,
                max_file_tokens=max_file_tokens,
                max_file_count=max_file_count,
                max_total_tokens=max_total_tokens,
                gitignore=gitignore,
            )

        _notify_on_changes(result)

        if not result["files"] and result["skipped_count"] == 0:
            prompt = self.agent.read_prompt(
                "agent.system.promptinclude.md",
                name_pattern=name_pattern,
                trusted_dir=files.get_abs_path(TRUSTED_DIR),
                includes="",
            )
            system_prompt.append(prompt)
            return

        includes = _format_includes(self.agent, result)
        prompt = self.agent.read_prompt(
            "agent.system.promptinclude.md",
            name_pattern=name_pattern,
            trusted_dir=files.get_abs_path(TRUSTED_DIR),
            includes=includes,
        )
        system_prompt.append(prompt)


def _resolve_scan_roots(agent: Agent) -> list[str]:
    trusted = files.get_abs_path(TRUSTED_DIR)
    try:
        os.makedirs(trusted, exist_ok=True)
    except OSError:
        pass
    roots = [trusted]
    project_name = projects.get_context_project_name(agent.context)
    if project_name:
        folder = projects.get_project_folder(project_name)
        if runtime.is_development():
            folder = files.normalize_a0_path(folder)
        roots.append(folder)
    return roots


def _notify_on_changes(result: ScanResult) -> None:
    """Tell the user when an include appears or changes, so an unexpected
    addition to the system prompt never goes unnoticed. The first scan after
    startup only records the baseline."""
    global _seen_hashes
    current = {
        entry["path"]: hashlib.sha256(entry.get("content", "").encode("utf-8")).hexdigest()
        for entry in result.get("files", [])
    }
    with _seen_lock:
        previous = _seen_hashes
        _seen_hashes = current
    if previous is None:
        return
    changed = [p for p, h in current.items() if previous.get(p) != h]
    if not changed:
        return
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType

        NotificationManager.send_notification(
            type=NotificationType.WARNING,
            priority=NotificationPriority.NORMAL,
            title="Prompt include added or changed",
            message=f"{len(changed)} prompt include file(s) now in the system prompt.",
            detail="\n".join(changed),
            display_time=10,
            group="promptinclude_changed",
        )
    except Exception:
        pass


def _format_includes(agent: Agent, result: ScanResult) -> str:
    lines: list[str] = []

    for entry in result["files"]:
        if entry["status"] == "skipped":
            lines.append(f"{entry['path']} !!! skipped to fit")
            continue

        suffix = " !!! cropped to fit" if entry["status"] == "cropped" else ""
        block = agent.read_prompt(
            "fw.promptinclude.includes.md",
            path=entry["path"],
            suffix=suffix,
            content=entry["content"],
        )
        lines.append(block)

    if result["skipped_count"] > 0:
        lines.append(f"!!! {result['skipped_count']} more files skipped to fit")

    return "\n".join(lines)
