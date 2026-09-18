from helpers.extension import Extension
from helpers import debounced, errors, plugins, files, runtime
from helpers import projects
from helpers.settings import get_settings
from agent import Agent, LoopData

from plugins._promptinclude.helpers.scanner import scan_promptinclude_files, ScanResult

# scan_promptinclude_files is a real recursive filesystem walk. Outside
# dev-Docker mode (see the branch below), runtime.call_development_function
# called it directly, synchronously, on the event loop, on every single
# prepare_prompt call - blocking the whole server for the walk's duration
# regardless of whether anything under the workdir had changed.
PROMPTINCLUDE_SCAN_TTL_SECONDS = 10.0


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
        # filesystem scan of the working directory - the same directory
        # code_execution_tool and text_editor are actively mutating while
        # the agent runs. A permission error, a vanished project folder, an
        # RFC/dev-mode connection drop, or a missing prompt template here
        # would otherwise propagate out of call_extensions_async (which has
        # no per-extension handling of its own) and break prompt assembly
        # for every future turn, not just this one - unlike a failure on a
        # message_loop_prompts_after extension, which only costs a turn.
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
        scan_path = _resolve_workdir(self.agent)

        if not scan_path:
            return

        name_pattern = config.get("name_pattern", "*.promptinclude.md")
        max_depth = config.get("max_depth", 10)
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
                scan_path,
                name_pattern=name_pattern,
                max_depth=max_depth,
                max_file_tokens=max_file_tokens,
                max_file_count=max_file_count,
                max_total_tokens=max_total_tokens,
                gitignore=gitignore,
            )
        else:
            # Windows, or a non-dev/production deployment: this used to
            # be a direct synchronous call on the event loop.
            # scan_promptinclude_files has "No agent/tool dependencies"
            # (its own docstring) so it is safe on a worker thread, and
            # debounced since the result rarely changes turn-to-turn.
            cache_key = (
                f"promptinclude:{scan_path}:{name_pattern}:{max_depth}:"
                f"{max_file_tokens}:{max_file_count}:{max_total_tokens}:{gitignore}"
            )
            result = await debounced.run_debounced(
                cache_key,
                PROMPTINCLUDE_SCAN_TTL_SECONDS,
                scan_promptinclude_files,
                scan_path,
                name_pattern=name_pattern,
                max_depth=max_depth,
                max_file_tokens=max_file_tokens,
                max_file_count=max_file_count,
                max_total_tokens=max_total_tokens,
                gitignore=gitignore,
            )

        if not result["files"] and result["skipped_count"] == 0:
            prompt = self.agent.read_prompt(
                "agent.system.promptinclude.md",
                name_pattern=name_pattern,
                includes="",
            )
            system_prompt.append(prompt)
            return

        includes = _format_includes(self.agent, result)
        prompt = self.agent.read_prompt(
            "agent.system.promptinclude.md",
            name_pattern=name_pattern,
            includes=includes,
        )
        system_prompt.append(prompt)


def _resolve_workdir(agent: Agent) -> str:
    project_name = projects.get_context_project_name(agent.context)
    if project_name:
        folder = projects.get_project_folder(project_name)
        if runtime.is_development():
            folder = files.normalize_a0_path(folder)
        return folder
    return get_settings()["workdir_path"]


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
