import os
from pathlib import Path
import shutil
import base64
import subprocess
from typing import Dict, List, Tuple, Any
from helpers.security import safe_filename
from datetime import datetime

from helpers import files
from helpers.localization import Localization
from helpers.print_style import PrintStyle


class FileBrowser:
    ALLOWED_EXTENSIONS = {
        'image': {'jpg', 'jpeg', 'png', 'bmp'},
        'code': {'py', 'js', 'sh', 'html', 'css'},
        'document': {'md', 'pdf', 'txt', 'csv', 'json'}
    }

    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    MAX_TEXT_FILE_SIZE = 1 * 1024 * 1024  # 1MB

    def __init__(self):
        from helpers import settings

        base_dir = settings.get_settings()["workdir_path"]
        self.base_dir = Path(base_dir).resolve()

    def _check_file_size(self, file) -> bool:
        try:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            return size <= self.MAX_FILE_SIZE
        except (AttributeError, IOError):
            return False

    def save_file_b64(self, current_path: str, filename: str, base64_content: str):
        try:
            # Resolve the target directory path
            target_file = (self.base_dir / current_path / filename).resolve()
            if not str(target_file).startswith(str(self.base_dir)):
                raise ValueError("Invalid target directory")

            os.makedirs(target_file.parent, exist_ok=True)
            # Save file
            with open(target_file, "wb") as file:
                file.write(base64.b64decode(base64_content))
            return True
        except Exception as e:
            PrintStyle.error(f"Error saving file {filename}: {e}")
            return False

    def save_files(self, files: List, current_path: str = "") -> Tuple[List[str], List[str]]:
        """Save uploaded files and return successful and failed filenames"""
        successful = []
        failed = []

        try:
            # Resolve the target directory path
            target_dir = (self.base_dir / current_path).resolve()
            if not str(target_dir).startswith(str(self.base_dir)):
                raise ValueError("Invalid target directory")

            os.makedirs(target_dir, exist_ok=True)

            for file in files:
                try:
                    if file and self._is_allowed_file(file.filename, file):
                        filename = safe_filename(file.filename)
                        if not filename:
                            raise ValueError("Invalid filename")
                        file_path = target_dir / filename

                        file.save(str(file_path))
                        successful.append(filename)
                    else:
                        failed.append(file.filename)
                except Exception as e:
                    PrintStyle.error(f"Error saving file {file.filename}: {e}")
                    failed.append(file.filename)

            return successful, failed

        except Exception as e:
            PrintStyle.error(f"Error in save_files: {e}")
            return successful, failed

    def delete_file(self, file_path: str) -> bool:
        """Delete a file or empty directory"""
        try:
            # Resolve the full path while preventing directory traversal
            full_path = (self.base_dir / file_path).resolve()
            if not str(full_path).startswith(str(self.base_dir)):
                raise ValueError("Invalid path")

            if os.path.exists(full_path):
                if os.path.isfile(full_path):
                    os.remove(full_path)
                elif os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                return True

            return False

        except Exception as e:
            PrintStyle.error(f"Error deleting {file_path}: {e}")
            return False

    def rename_item(self, file_path: str, new_name: str) -> bool:
        try:
            if not new_name or new_name in {".", ".."}:
                raise ValueError("Invalid new name")
            if "/" in new_name or "\\" in new_name:
                raise ValueError("New name cannot include path separators")

            full_path = (self.base_dir / file_path).resolve()
            if not str(full_path).startswith(str(self.base_dir)):
                raise ValueError("Invalid path")
            if not full_path.exists():
                raise FileNotFoundError("File or folder not found")

            new_path = full_path.with_name(new_name)
            if not str(new_path).startswith(str(self.base_dir)):
                raise ValueError("Invalid target path")
            if full_path == new_path:
                return True
            if new_path.exists():
                raise FileExistsError("Target already exists")

            os.rename(full_path, new_path)
            return True
        except Exception as e:
            PrintStyle.error(f"Error renaming {file_path}: {e}")
            raise

    def create_folder(self, parent_path: str, folder_name: str) -> bool:
        try:
            if not folder_name or folder_name in {".", ".."}:
                raise ValueError("Invalid folder name")
            if "/" in folder_name or "\\" in folder_name:
                raise ValueError("Folder name cannot include path separators")

            parent_full = (self.base_dir / parent_path).resolve()
            if not str(parent_full).startswith(str(self.base_dir)):
                raise ValueError("Invalid parent path")

            target_dir = (parent_full / folder_name).resolve()
            if not str(target_dir).startswith(str(self.base_dir)):
                raise ValueError("Invalid target path")
            if target_dir.exists():
                raise FileExistsError("Folder already exists")

            os.makedirs(target_dir, exist_ok=False)
            return True
        except Exception as e:
            PrintStyle.error(f"Error creating folder {folder_name}: {e}")
            raise

    def save_text_file(self, file_path: str, content: str) -> bool:
        try:
            if not isinstance(content, str):
                raise ValueError("Content must be a string")
            content_size = len(content.encode("utf-8"))
            if content_size > self.MAX_TEXT_FILE_SIZE:
                raise ValueError("File exceeds 1 MB and cannot be edited")

            full_path = (self.base_dir / file_path).resolve()
            if not str(full_path).startswith(str(self.base_dir)):
                raise ValueError("Invalid path")
            if full_path.exists() and full_path.is_dir():
                raise ValueError("Target is a directory")

            os.makedirs(full_path.parent, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file:
                file.write(content)
            return True
        except Exception as e:
            PrintStyle.error(f"Error saving file {file_path}: {e}")
            raise

    def _is_allowed_file(self, filename: str, file) -> bool:
        # allow any file to be uploaded in file browser

        # if not filename:
        #     return False
        # ext = self._get_file_extension(filename)
        # all_allowed = set().union(*self.ALLOWED_EXTENSIONS.values())
        # if ext not in all_allowed:
        #     return False

        return True  # Allow the file if it passes the checks

    def _get_file_extension(self, filename: str) -> str:
        return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

    def _get_files_via_ls(self, full_path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Cross-platform directory enumeration using native Python APIs."""
        file_entries: List[Dict[str, Any]] = []
        folders: List[Dict[str, Any]] = []

        try:
            with os.scandir(full_path) as iterator:
                for entry in iterator:
                    if entry.name in {".", ".."}:
                        continue

                    try:
                        stat_info = entry.stat(follow_symlinks=True)
                        entry_path = Path(entry.path).resolve()

                        relative_path = entry_path.relative_to(
                            self.base_dir
                        ).as_posix()

                        entry_data: Dict[str, Any] = {
                            "name": entry.name,
                            "path": relative_path,
                            "modified": datetime.fromtimestamp(
                                stat_info.st_mtime,
                                tz=Localization.get().get_tzinfo(),
                            ).isoformat(),
                        }

                        if entry.is_symlink():
                            entry_data["is_symlink"] = True

                        if entry.is_dir(follow_symlinks=True):
                            entry_data.update({
                                "type": "folder",
                                "size": 0,
                                "is_dir": True,
                            })

                            folders.append(entry_data)

                        elif entry.is_file(follow_symlinks=True):
                            entry_data.update({
                                "type": self._get_file_type(entry.name),
                                "size": stat_info.st_size,
                                "is_dir": False,
                            })

                            file_entries.append(entry_data)

                        if len(file_entries) + len(folders) > 10000:
                            break

                    except (
                        OSError,
                        PermissionError,
                        FileNotFoundError,
                        ValueError
                    ) as exc:

                        PrintStyle.warning(
                            f"No access to {entry.name}: {exc}"
                        )

                        continue

        except (
            OSError,
            PermissionError,
            FileNotFoundError
        ) as exc:

            PrintStyle.error(
                f"Error reading directory {full_path}: {exc}"
            )

        folders.sort(
            key=lambda item: item["name"].lower()
        )

        file_entries.sort(
            key=lambda item: item["name"].lower()
        )

        return file_entries, folders
    def get_files(self, current_path: str = "") -> Dict:
        try:
            # Resolve the full path while preventing directory traversal
            full_path = (self.base_dir / current_path).resolve()
            if not str(full_path).startswith(str(self.base_dir)):
                raise ValueError("Invalid path")
            if not full_path.exists():
                raise FileNotFoundError("Directory not found")
            if not full_path.is_dir():
                raise NotADirectoryError("Path is not a directory")

            # Use ls command instead of os.scandir for better error handling
            files, folders = self._get_files_via_ls(full_path)

            # Combine folders and files, folders first
            all_entries = folders + files

            # Get parent directory path if not at root
            parent_path = ""
            if current_path:
                try:
                    # Get the absolute path of current directory
                    current_abs = (self.base_dir / current_path).resolve()

                    # parent_path is empty only if we're already at root
                    if str(current_abs) != str(self.base_dir):
                        parent_path = str(Path(current_path).parent)

                except Exception:
                    parent_path = ""

            return {
                "entries": all_entries,
                "current_path": current_path,
                "parent_path": parent_path
            }

        except Exception as e:
            PrintStyle.error(f"Error reading directory: {e}")
            return {
                "entries": [],
                "current_path": current_path,
                "parent_path": "",
                "error": str(e),
            }

    def get_full_path(self, file_path: str, allow_dir: bool = False) -> str:
        """Get full file path if it exists and is within base_dir"""
        full_path = files.get_abs_path(self.base_dir, file_path)
        if not files.exists(full_path):
            raise ValueError(f"File {file_path} not found")
        return full_path

    def _get_file_type(self, filename: str) -> str:
        ext = self._get_file_extension(filename)
        for file_type, extensions in self.ALLOWED_EXTENSIONS.items():
            if ext in extensions:
                return file_type
        return 'unknown'


