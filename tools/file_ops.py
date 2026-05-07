"""File management tools — read, write, edit, search, and manipulate files."""

import difflib
import os
import shutil
import stat
import tarfile
import time
import zipfile
from typing import Any, Dict, List, Optional

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Helper utilities (private)
# =====================================================================

def _resolve_path(path: str) -> str:
    """Return an absolute, expanded path."""
    return os.path.abspath(os.path.expanduser(path))


def _check_readable(path: str) -> Dict[str, Any]:
    """Return an error-dict if *path* is not readable, else *None*."""
    if not os.path.exists(path):
        return {"error": f"Path does not exist: {path}"}
    if not os.path.isfile(path):
        return {"error": f"Not a file: {path}"}
    if not os.access(path, os.R_OK):
        return {"error": f"Permission denied: {path}"}
    return None


def _format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _safe_stat(path: str) -> Optional[os.stat_result]:
    try:
        return os.stat(path)
    except OSError:
        return None


# =====================================================================
# Tool implementations
# =====================================================================

def read_file(
    path: str,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Read the contents of a text file with optional offset/limit."""
    path = _resolve_path(path)
    err = _check_readable(path)
    if err:
        return err

    st = _safe_stat(path)
    file_size = st.st_size if st else 0

    # Heuristic: try text mode first; fall back to showing binary info.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except Exception as exc:
        return {"error": f"Could not read file: {exc}"}

    total_lines = len(lines)
    start = offset if offset is not None else 0
    start = max(0, start)

    if limit is not None:
        end = start + limit
    else:
        end = total_lines
    selected = lines[start:end]

    # Build numbered output
    numbered = []
    for i, line in enumerate(selected, start=start + 1):
        numbered.append(f"{i:>6}\t{line.rstrip('\n\r')}")
    content = "\n".join(numbered)

    preview = ""
    if offset is not None or limit is not None:
        preview = f" (showing lines {start + 1}–{min(end, total_lines)} of {total_lines})"
    else:
        if total_lines > 200:
            preview = f" ({total_lines} lines — file is large; consider using offset/limit)"

    return {
        "output": content,
        "display": content,
        "data": {
            "path": path,
            "size": file_size,
            "total_lines": total_lines,
            "shown_lines": len(selected),
            "encoding": "utf-8",
        },
    }


def write_file(
    path: str,
    content: str,
    create_dirs: bool = False,
) -> Dict[str, Any]:
    """Write *content* to *path*, optionally creating parent directories."""
    path = _resolve_path(path)

    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        if create_dirs:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as exc:
                return {"error": f"Could not create directories {parent}: {exc}"}
        else:
            return {"error": f"Parent directory does not exist: {parent}. Set create_dirs=true to create it."}

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as exc:
        return {"error": f"Could not write file {path}: {exc}"}

    written = len(content.encode("utf-8"))
    return {
        "output": f"Written {written} bytes to {path}",
        "data": {"path": path, "bytes_written": written},
    }


def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> Dict[str, Any]:
    """Find-and-replace in *path*. Shows a diff preview."""
    path = _resolve_path(path)
    err = _check_readable(path)
    if err:
        return err

    if not os.access(path, os.W_OK):
        return {"error": f"Permission denied (read-only): {path}"}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        original = fh.read()

    if old_text not in original:
        return {"error": "old_text not found in file — no changes made."}

    if replace_all:
        occurrences = original.count(old_text)
        modified = original.replace(old_text, new_text)
    else:
        occurrences = 1
        modified = original.replace(old_text, new_text, 1)

    # Generate unified diff
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
        lineterm="",
    ))
    diff_text = "\n".join(diff_lines) if diff_lines else "(no visible diff)"

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(modified)
    except OSError as exc:
        return {"error": f"Could not write file: {exc}"}

    return {
        "output": f"Replaced {occurrences} occurrence(s) in {path}",
        "display": diff_text,
        "data": {
            "path": path,
            "occurrences": occurrences,
            "replace_all": replace_all,
        },
    }


def list_directory(
    path: str,
    show_hidden: bool = False,
    recursive: bool = False,
) -> Dict[str, Any]:
    """List directory contents with metadata."""
    path = _resolve_path(path)

    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}

    entries: List[Dict[str, Any]] = []

    def _scan(directory: str, prefix: str = "") -> None:
        try:
            items = sorted(os.listdir(directory))
        except PermissionError as exc:
            return
        for item in items:
            if item.startswith(".") and not show_hidden:
                continue
            full = os.path.join(directory, item)
            rel = os.path.join(prefix, item) if prefix else item
            st = _safe_stat(full)
            if st is None:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            entries.append({
                "name": rel,
                "type": "directory" if is_dir else "file",
                "size": st.st_size if not is_dir else None,
                "size_human": _format_size(st.st_size) if not is_dir else "<DIR>",
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            })
            if recursive and is_dir and item not in (".", ".."):
                _scan(full, rel)

    _scan(path)

    if not entries:
        return {"output": "(empty directory)", "data": {"path": path, "entries": []}}

    lines = []
    for e in entries:
        mod = f"  {e['modified']}" if e.get("modified") else ""
        lines.append(f"{e['type']:<10}{e['size_human']:<10}{e['name']}{mod}")
    display = "\n".join(lines)

    return {
        "output": f"{len(entries)} item(s) in {path}",
        "display": display,
        "data": {"path": path, "entries": entries},
    }


def search_files(
    pattern: str,
    path: Optional[str] = None,
    search_content: bool = False,
    file_glob: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for files by name pattern or file content."""
    base = _resolve_path(path) if path else os.getcwd()
    if not os.path.isdir(base):
        return {"error": f"Not a directory: {base}"}

    pattern_lower = pattern.lower()
    matches: List[Dict[str, Any]] = []
    max_results = 200
    max_file_size = 10 * 1024 * 1024  # 10 MB

    for root, dirs, files in os.walk(base):
        for fname in files:
            # Name filter
            if file_glob:
                # Simple glob: support * and ? at ends/positions
                import fnmatch
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
            if pattern_lower not in fname.lower():
                continue

            full = os.path.join(root, fname)
            rel = os.path.relpath(full, base)
            st = _safe_stat(full)
            if st is None:
                continue

            entry: Dict[str, Any] = {
                "path": rel,
                "size": st.st_size,
                "size_human": _format_size(st.st_size),
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            }

            # Content search
            if search_content and st.st_size <= max_file_size:
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if pattern_lower in line.lower():
                                entry["match_line"] = lineno
                                entry["match_preview"] = line.strip()[:200]
                                break
                except Exception:
                    pass

            matches.append(entry)
            if len(matches) >= max_results:
                break
        if len(matches) >= max_results:
            break

    if not matches:
        return {"output": f"No files matching '{pattern}' found in {base}"}

    lines = []
    for m in matches:
        extra = f"  line {m['match_line']}: {m.get('match_preview', '')}" if "match_line" in m else ""
        lines.append(f"{m['size_human']:<10}{m['path']}{extra}")
    display = "\n".join(lines)

    return {
        "output": f"Found {len(matches)} file(s) matching '{pattern}' in {base}",
        "display": display,
        "data": {"base": base, "matches": matches},
    }


def file_info(path: str) -> Dict[str, Any]:
    """Return detailed metadata for a file or directory."""
    path = _resolve_path(path)
    if not os.path.exists(path):
        return {"error": f"Path does not exist: {path}"}

    st = _safe_stat(path)
    if st is None:
        return {"error": f"Cannot stat: {path}"}

    is_dir = stat.S_ISDIR(st.st_mode)
    is_file = stat.S_ISREG(st.st_mode)
    is_link = stat.S_ISLNK(st.st_mode)

    perms = stat.filemode(st.st_mode)

    info: Dict[str, Any] = {
        "path": path,
        "type": "directory" if is_dir else ("symlink" if is_link else "file"),
        "size": st.st_size,
        "size_human": _format_size(st.st_size),
        "permissions": perms,
        "owner_uid": st.st_uid,
        "owner_gid": st.st_gid,
        "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "accessed": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_atime)),
        "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_ctime)),
    }

    # Extension
    if is_file:
        _, ext = os.path.splitext(path)
        info["extension"] = ext.lower() if ext else "(none)"

    lines = []
    for k, v in info.items():
        lines.append(f"{k:<16}{v}")
    display = "\n".join(lines)

    return {
        "output": f"Info for {path}",
        "display": display,
        "data": info,
    }


def compare_files(path1: str, path2: str) -> Dict[str, Any]:
    """Compare two files and return a unified diff."""
    path1 = _resolve_path(path1)
    path2 = _resolve_path(path2)

    err1 = _check_readable(path1)
    err2 = _check_readable(path2)
    if err1:
        return err1
    if err2:
        return err2

    try:
        with open(path1, "r", encoding="utf-8", errors="replace") as fh:
            lines1 = fh.readlines()
    except Exception as exc:
        return {"error": f"Could not read {path1}: {exc}"}
    try:
        with open(path2, "r", encoding="utf-8", errors="replace") as fh:
            lines2 = fh.readlines()
    except Exception as exc:
        return {"error": f"Could not read {path2}: {exc}"}

    diff = list(difflib.unified_diff(
        lines1, lines2,
        fromfile=path1,
        tofile=path2,
        lineterm="",
    ))

    if not diff:
        return {"output": "Files are identical.", "data": {"identical": True, "path1": path1, "path2": path2}}

    diff_text = "\n".join(diff)
    # Count changes
    additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    return {
        "output": f"Differences found: {additions} addition(s), {deletions} deletion(s)",
        "display": diff_text,
        "data": {
            "identical": False,
            "path1": path1,
            "path2": path2,
            "additions": additions,
            "deletions": deletions,
            "diff_lines": len(diff),
        },
    }


def compress_files(
    paths: List[str],
    output: str,
    format: str = "zip",
) -> Dict[str, Any]:
    """Create an archive (zip/tar/gztar) from the given paths."""
    output = _resolve_path(output)
    parent = os.path.dirname(output)
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return {"error": f"Could not create output directory: {exc}"}

    resolved_paths = [_resolve_path(p) for p in paths]
    for rp in resolved_paths:
        if not os.path.exists(rp):
            return {"error": f"Path does not exist: {rp}"}

    try:
        if format == "zip":
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
                for rp in resolved_paths:
                    if os.path.isfile(rp):
                        zf.write(rp, os.path.basename(rp))
                    elif os.path.isdir(rp):
                        for root, dirs, files in os.walk(rp):
                            for f in files:
                                full = os.path.join(root, f)
                                arcname = os.path.relpath(full, os.path.dirname(rp))
                                zf.write(full, arcname)

        elif format in ("tar", "gztar"):
            mode = "w:gz" if format == "gztar" else "w"
            with tarfile.open(output, mode) as tf:
                for rp in resolved_paths:
                    if os.path.isfile(rp):
                        tf.add(rp, arcname=os.path.basename(rp))
                    elif os.path.isdir(rp):
                        tf.add(rp, arcname=os.path.basename(rp))
        else:
            return {"error": f"Unsupported format '{format}'. Use zip, tar, or gztar."}

        st = _safe_stat(output)
        size = _format_size(st.st_size) if st else "?"

        return {
            "output": f"Archive created: {output} ({size})",
            "data": {"output": output, "format": format, "source_paths": paths},
        }
    except Exception as exc:
        return {"error": f"Failed to create archive: {exc}"}


def move_file(source: str, destination: str) -> Dict[str, Any]:
    """Move or rename a file/directory."""
    source = _resolve_path(source)
    destination = _resolve_path(destination)

    if not os.path.exists(source):
        return {"error": f"Source does not exist: {source}"}

    dest_parent = os.path.dirname(destination)
    if dest_parent and not os.path.isdir(dest_parent):
        return {"error": f"Destination parent directory does not exist: {dest_parent}"}

    if os.path.exists(destination):
        return {"error": f"Destination already exists: {destination}"}

    try:
        shutil.move(source, destination)
        return {
            "output": f"Moved {source} → {destination}",
            "data": {"source": source, "destination": destination},
        }
    except Exception as exc:
        return {"error": f"Failed to move: {exc}"}


def delete_file(path: str) -> Dict[str, Any]:
    """Delete a file or empty directory."""
    path = _resolve_path(path)
    if not os.path.exists(path):
        return {"error": f"Path does not exist: {path}"}

    try:
        if os.path.isdir(path):
            # Only delete if empty
            if os.listdir(path):
                return {"error": f"Directory is not empty: {path}. Remove contents first."}
            os.rmdir(path)
            return {"output": f"Deleted directory: {path}", "data": {"path": path}}
        else:
            os.remove(path)
            return {"output": f"Deleted file: {path}", "data": {"path": path}}
    except Exception as exc:
        return {"error": f"Failed to delete: {exc}"}


# =====================================================================
# Registration helper — called by ToolRegistry.register_defaults()
# =====================================================================

_FILE_TOOLS = [
    (
        "read_file",
        "Read the contents of a file. Supports offset/limit for large files. "
        "Shows line numbers.",
        [
            ToolParameter("path", "string", "Path to the file to read"),
            ToolParameter("offset", "integer", "Starting line number (0-based)", required=False, default=None),
            ToolParameter("limit", "integer", "Maximum number of lines to read", required=False, default=None),
        ],
        read_file,
        False,
    ),
    (
        "write_file",
        "Write content to a file. Creates or overwrites the file.",
        [
            ToolParameter("path", "string", "Path to the file to write"),
            ToolParameter("content", "string", "Content to write to the file"),
            ToolParameter("create_dirs", "boolean", "Create parent directories if needed", required=False, default=False),
        ],
        write_file,
        True,
    ),
    (
        "edit_file",
        "Find and replace text in a file. Shows a diff preview of changes.",
        [
            ToolParameter("path", "string", "Path to the file to edit"),
            ToolParameter("old_text", "string", "Text to find"),
            ToolParameter("new_text", "string", "Replacement text"),
            ToolParameter("replace_all", "boolean", "Replace all occurrences", required=False, default=False),
        ],
        edit_file,
        True,
    ),
    (
        "list_directory",
        "List directory contents with file sizes, types, and timestamps.",
        [
            ToolParameter("path", "string", "Path to the directory"),
            ToolParameter("show_hidden", "boolean", "Show hidden files", required=False, default=False),
            ToolParameter("recursive", "boolean", "List recursively", required=False, default=False),
        ],
        list_directory,
        False,
    ),
    (
        "search_files",
        "Search for files by name pattern. Optionally search within file contents.",
        [
            ToolParameter("pattern", "string", "Search pattern (substring match on filename)"),
            ToolParameter("path", "string", "Directory to search in", required=False, default=None),
            ToolParameter("search_content", "boolean", "Also search within file contents", required=False, default=False),
            ToolParameter("file_glob", "string", "File glob filter (e.g. '*.py')", required=False, default=None),
        ],
        search_files,
        False,
    ),
    (
        "file_info",
        "Get detailed metadata for a file or directory (size, permissions, dates).",
        [
            ToolParameter("path", "string", "Path to the file or directory"),
        ],
        file_info,
        False,
    ),
    (
        "compare_files",
        "Compare two files and show a unified diff of their differences.",
        [
            ToolParameter("path1", "string", "Path to the first file"),
            ToolParameter("path2", "string", "Path to the second file"),
        ],
        compare_files,
        False,
    ),
    (
        "compress_files",
        "Create a zip, tar, or gzipped tar archive from files/directories.",
        [
            ToolParameter("paths", "array", "List of file/directory paths to archive"),
            ToolParameter("output", "string", "Output path for the archive"),
            ToolParameter("format", "string", "Archive format: zip, tar, or gztar", required=False, default="zip",
                          enum=["zip", "tar", "gztar"]),
        ],
        compress_files,
        True,
    ),
    (
        "move_file",
        "Move or rename a file or directory.",
        [
            ToolParameter("source", "string", "Source path"),
            ToolParameter("destination", "string", "Destination path"),
        ],
        move_file,
        True,
    ),
    (
        "delete_file",
        "Delete a file or empty directory.",
        [
            ToolParameter("path", "string", "Path to delete"),
        ],
        delete_file,
        True,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all file-operation tools with the given registry."""
    for name, desc, params, func, dangerous in _FILE_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
