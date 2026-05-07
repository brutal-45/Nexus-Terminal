"""Git operation tools."""

import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Helpers
# =====================================================================

def _resolve(path: Optional[str]) -> str:
    if path:
        return os.path.abspath(os.path.expanduser(path))
    return os.getcwd()


def _git(*args: str, cwd: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command and return the CompletedProcess."""
    cmd = ["git"] + list(args)
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, -1, "", "git is not installed")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, -1, "", "git command timed out")


def _git_ok(*args, **kwargs) -> bool:
    """Return True if a git command succeeded."""
    return _git(*args, **kwargs).returncode == 0


# =====================================================================
# Tool implementations
# =====================================================================

def git_status(path: Optional[str] = None) -> Dict[str, Any]:
    """Show the working tree status."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    result = _git("status", "--short", "--branch", cwd=cwd)
    if result.returncode != 0:
        return {"error": f"git status failed: {result.stderr.strip() or 'not a git repo'}"}

    output = result.stdout.strip()
    if not output:
        output = "(clean working tree)"

    return {
        "output": output,
        "display": output,
        "data": {"path": cwd, "raw": result.stdout},
    }


def git_log(
    path: Optional[str] = None,
    count: int = 10,
    author: Optional[str] = None,
    oneline: bool = True,
) -> Dict[str, Any]:
    """Show commit history."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    args = ["log", f"-{count}"]
    if oneline:
        args.append("--oneline")
    if author:
        args.extend(["--author", author])
    args.append("--date=short", "--format=%h %ad %an %s")

    result = _git(*args, cwd=cwd)
    if result.returncode != 0:
        return {"error": f"git log failed: {result.stderr.strip() or 'not a git repo'}"}

    output = result.stdout.strip()
    if not output:
        output = "(no commits)"

    return {
        "output": output,
        "display": output,
        "data": {"path": cwd, "count": count, "author": author},
    }


def git_diff(
    path: Optional[str] = None,
    staged: bool = False,
    file: Optional[str] = None,
) -> Dict[str, Any]:
    """Show changes (diff)."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    args = ["diff"]
    if staged:
        args.append("--cached")
    if file:
        args.append("--")
        args.append(file)

    result = _git(*args, cwd=cwd)
    if result.returncode != 0:
        return {"error": f"git diff failed: {result.stderr.strip()}"}

    output = result.stdout.strip()
    if not output:
        msg = "No staged changes." if staged else "No unstaged changes."
        return {"output": msg, "data": {"path": cwd, "has_diff": False}}

    # Summary stats
    additions = 0
    deletions = 0
    files_changed = 0
    for line in output.split("\n"):
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
        # Count file headers for files changed
        if line.startswith("diff --git"):
            files_changed += 1

    return {
        "output": output,
        "display": output,
        "data": {
            "path": cwd,
            "staged": staged,
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed,
            "has_diff": True,
        },
    }


def git_branch(
    path: Optional[str] = None,
    action: str = "list",
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Branch operations: list, create, switch, delete."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    valid_actions = ("list", "create", "switch", "delete", "current")
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Use: {', '.join(valid_actions)}"}

    if action == "list":
        result = _git("branch", "-a", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        output = result.stdout.strip() or "(no branches)"
        # Mark current branch
        lines = output.split("\n")
        marked = []
        for l in lines:
            if l.startswith("* "):
                marked.append(f"  * {l[2:]}  (current)")
            else:
                marked.append(f"    {l.strip()}")
        display = "\n".join(marked)
        return {"output": output, "display": display, "data": {"path": cwd}}

    elif action == "create":
        if not name:
            return {"error": "'name' is required for create action."}
        result = _git("branch", name, cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": f"Branch '{name}' created.", "data": {"name": name}}

    elif action == "switch":
        if not name:
            return {"error": "'name' is required for switch action."}
        result = _git("checkout", name, cwd=cwd)
        if result.returncode != 0:
            # Try git switch
            result2 = _git("switch", name, cwd=cwd)
            if result2.returncode != 0:
                return {"error": f"Failed to switch: {result.stderr.strip() or result2.stderr.strip()}"}
        return {"output": f"Switched to branch '{name}'.", "data": {"name": name}}

    elif action == "delete":
        if not name:
            return {"error": "'name' is required for delete action."}
        result = _git("branch", "-d", name, cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": f"Branch '{name}' deleted.", "data": {"name": name}}

    elif action == "current":
        result = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        branch = result.stdout.strip()
        return {"output": f"Current branch: {branch}", "data": {"branch": branch}}

    return {"error": "Unknown action."}


def git_commit(
    path: Optional[str] = None,
    message: str = "",
    files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a git commit."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    if not message or not message.strip():
        return {"error": "Commit message is required."}

    message = message.strip()

    # Stage files if specified
    if files:
        for f in files:
            fpath = os.path.join(cwd, f) if not os.path.isabs(f) else f
            result = _git("add", fpath, cwd=cwd)
            if result.returncode != 0:
                return {"error": f"Failed to stage {f}: {result.stderr.strip()}"}

    result = _git("commit", "-m", message, cwd=cwd)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "nothing to commit" in stderr:
            return {"output": "Nothing to commit.", "data": {"committed": False}}
        return {"error": stderr}

    # Get commit hash
    hash_result = _git("rev-parse", "--short", "HEAD", cwd=cwd)
    short_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else "?"

    return {
        "output": f"Committed: {short_hash} — {message}",
        "data": {"hash": short_hash, "message": message, "files": files},
    }


def git_add(
    path: Optional[str] = None,
    files: List[str] = None,
) -> Dict[str, Any]:
    """Stage files for commit."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    if not files:
        return {"error": "No files specified."}

    staged = []
    for f in files:
        result = _git("add", f, cwd=cwd)
        if result.returncode != 0:
            return {"error": f"Failed to stage {f}: {result.stderr.strip()}"}
        staged.append(f)

    return {
        "output": f"Staged {len(staged)} file(s): {', '.join(staged)}",
        "data": {"staged": staged},
    }


def git_stash(
    path: Optional[str] = None,
    action: str = "list",
) -> Dict[str, Any]:
    """Stash operations: push, pop, list, drop."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    valid_actions = ("push", "pop", "list", "drop", "show")
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Use: {', '.join(valid_actions)}"}

    if action == "list":
        result = _git("stash", "list", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        output = result.stdout.strip() or "(no stashes)"
        return {"output": output, "display": output, "data": {"path": cwd}}

    elif action == "push":
        result = _git("stash", "push", "-m", "auto-stash", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": "Changes stashed.", "data": {"action": "push"}}

    elif action == "pop":
        result = _git("stash", "pop", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": "Stash popped.", "data": {"action": "pop"}}

    elif action == "drop":
        result = _git("stash", "drop", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": "Stash dropped.", "data": {"action": "drop"}}

    elif action == "show":
        result = _git("stash", "show", "-p", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip() or "No stashes."}
        output = result.stdout.strip() or "(empty stash)"
        return {"output": output, "display": output, "data": {"action": "show"}}

    return {"error": "Unknown action."}


def git_remote(
    path: Optional[str] = None,
    action: str = "list",
    name: Optional[str] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    """Remote operations: list, add, remove, show URL."""
    cwd = _resolve(path)
    if not os.path.isdir(cwd):
        return {"error": f"Directory not found: {cwd}"}

    valid_actions = ("list", "add", "remove", "url")
    if action not in valid_actions:
        return {"error": f"Invalid action '{action}'. Use: {', '.join(valid_actions)}"}

    if action == "list":
        result = _git("remote", "-v", cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        output = result.stdout.strip() or "(no remotes)"
        return {"output": output, "display": output, "data": {"path": cwd}}

    elif action == "url":
        if not name:
            name = "origin"
        result = _git("remote", "get-url", name, cwd=cwd)
        if result.returncode != 0:
            return {"error": f"No remote named '{name}' or not a git repo."}
        remote_url = result.stdout.strip()
        return {"output": f"{name}: {remote_url}", "data": {"name": name, "url": remote_url}}

    elif action == "add":
        if not name:
            return {"error": "'name' is required for add action."}
        if not url:
            return {"error": "'url' is required for add action."}
        result = _git("remote", "add", name, url, cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": f"Remote '{name}' added: {url}", "data": {"name": name, "url": url}}

    elif action == "remove":
        if not name:
            return {"error": "'name' is required for remove action."}
        result = _git("remote", "remove", name, cwd=cwd)
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": f"Remote '{name}' removed.", "data": {"name": name}}

    return {"error": "Unknown action."}


# =====================================================================
# Registration
# =====================================================================

_GIT_TOOLS = [
    (
        "git_status",
        "Show the working tree status (modified, staged, untracked files).",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
        ],
        git_status,
        False,
    ),
    (
        "git_log",
        "Show commit history. Can filter by author and limit count.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("count", "integer", "Number of commits to show", required=False, default=10),
            ToolParameter("author", "string", "Filter by author name", required=False, default=None),
            ToolParameter("oneline", "boolean", "Show compact one-line format", required=False, default=True),
        ],
        git_log,
        False,
    ),
    (
        "git_diff",
        "Show changes (diff). Can show staged or unstaged changes, optionally for a specific file.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("staged", "boolean", "Show staged changes (git diff --cached)", required=False, default=False),
            ToolParameter("file", "string", "Show diff for a specific file only", required=False, default=None),
        ],
        git_diff,
        False,
    ),
    (
        "git_branch",
        "Branch operations: list, create, switch, delete, or show current branch.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("action", "string", "Action to perform", required=False, default="list",
                          enum=["list", "create", "switch", "delete", "current"]),
            ToolParameter("name", "string", "Branch name (for create/switch/delete)", required=False, default=None),
        ],
        git_branch,
        False,
    ),
    (
        "git_commit",
        "Create a git commit. Optionally stage specific files first.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("message", "string", "Commit message"),
            ToolParameter("files", "array", "Files to stage before committing", required=False, default=None),
        ],
        git_commit,
        True,
    ),
    (
        "git_add",
        "Stage files for the next commit.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("files", "array", "List of file paths to stage"),
        ],
        git_add,
        True,
    ),
    (
        "git_stash",
        "Stash operations: push, pop, list, drop, or show stash contents.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("action", "string", "Stash action", required=False, default="list",
                          enum=["push", "pop", "list", "drop", "show"]),
        ],
        git_stash,
        False,
    ),
    (
        "git_remote",
        "Remote operations: list, add, remove, or show remote URLs.",
        [
            ToolParameter("path", "string", "Repository path", required=False, default=None),
            ToolParameter("action", "string", "Remote action", required=False, default="list",
                          enum=["list", "add", "remove", "url"]),
            ToolParameter("name", "string", "Remote name (e.g. 'origin')", required=False, default=None),
            ToolParameter("url", "string", "Remote URL (for add action)", required=False, default=None),
        ],
        git_remote,
        False,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all git tools with the given registry."""
    for name, desc, params, func, dangerous in _GIT_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
