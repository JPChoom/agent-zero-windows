from helpers.extension import Extension, best_effort
from agent import LoopData
from helpers import projects
from helpers import settings
from helpers import runtime
from helpers import file_tree
from helpers import files
from helpers import debounced

# file_tree.file_tree() is a real recursive filesystem walk with no
# thread offload of its own, called on every single turn regardless of
# whether the workdir changed since the last one. A0 is a single-process
# asyncio server, so running it in-line blocked every other agent and
# every websocket message for the walk's duration, every turn, scaling
# with the directory's size. The debounce also means a burst of turns in
# a fast tool-call loop shares one walk instead of repeating it.
WORKDIR_TREE_TTL_SECONDS = 10.0

class IncludeWorkdirExtras(Extension):
    @best_effort("Workdir extras")
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        project_name = projects.get_context_project_name(self.agent.context)

        enabled = False
        max_depth = 0
        max_files = 0
        max_folders = 0
        max_lines = 0
        gitignore_raw = ""
        folder = ""
        file_structure = ""

        if project_name:
            project = projects.load_basic_project_data(project_name)
            enabled = project["file_structure"]["enabled"]
            
            if not enabled:
                return
            
            max_depth = project["file_structure"]["max_depth"]
            gitignore_raw = project["file_structure"]["gitignore"]

            folder = projects.get_project_folder(project_name)
            if runtime.is_development():
                folder = files.normalize_a0_path(folder)

            file_structure = projects.get_file_structure(project_name)
        else:
            set = settings.get_settings()
            enabled = bool(set["workdir_show"])

            if not enabled:
                return
            
            max_depth = set["workdir_max_depth"]
            max_files = set["workdir_max_files"]
            max_folders = set["workdir_max_folders"]
            max_lines = set["workdir_max_lines"]
            gitignore_raw = set["workdir_gitignore"]

            folder = set["workdir_path"]
            scan_path = files.get_abs_path_development(folder)

            files.create_dir(scan_path)

            # Keyed on every parameter that affects the result, so a
            # settings change (e.g. max_depth) gets a fresh walk rather
            # than serving a result computed under different limits.
            cache_key = (
                f"workdir_extras:{scan_path}:{max_depth}:{max_files}:"
                f"{max_folders}:{max_lines}:{gitignore_raw}"
            )
            file_structure = str(
                await debounced.run_debounced(
                    cache_key,
                    WORKDIR_TREE_TTL_SECONDS,
                    file_tree.file_tree,
                    scan_path,
                    max_depth=max_depth,
                    max_files=max_files,
                    max_folders=max_folders,
                    max_lines=max_lines,
                    ignore=gitignore_raw,
                    output_mode=file_tree.OUTPUT_MODE_STRING,
                )
            )

        gitignore = cleanup_gitignore(gitignore_raw)

        file_structure_prompt = self.agent.read_prompt(
            "agent.extras.workdir_structure.md",
            max_depth=max_depth,
            gitignore=gitignore,
            folder=folder,
            file_structure=file_structure,
        )

        loop_data.extras_temporary["project_file_structure"] = file_structure_prompt


def cleanup_gitignore(gitignore_raw: str) -> str:
    """Process gitignore: split lines, strip, remove comments, remove empty lines."""
    gitignore_lines = []
    for line in gitignore_raw.split('\n'):
        # Strip whitespace
        line = line.strip()
        # Remove inline comments (everything after #)
        if '#' in line:
            line = line.split('#')[0].strip()
        # Keep only non-empty lines
        if line:
            gitignore_lines.append(line)
    
    return '\n'.join(gitignore_lines) if gitignore_lines else "nothing ignored"
