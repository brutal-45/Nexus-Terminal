"""Intent parser for Nexus — quick-action pattern matching.

Provides a lightweight, regex-based intent recogniser that detects common
user requests (file listing, system info, git commands, etc.) and maps
them to tool calls without involving the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class IntentAction:
    """Represents a detected quick-action intent.

    Attributes:
        tool_name: Name of the tool to invoke.
        params: Parameters extracted from the user input.
        confidence: Confidence score between 0 and 1.
    """

    tool_name: str
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


# Type alias for the compiled pattern tuple
# Each entry: (compiled_regex, tool_name, param_extractor_function)
_PatternEntry = Tuple[re.Pattern[str], str, Callable[[re.Match[str]], Dict[str, Any]]]


class IntentParser:
    """Regex-based intent parser for quick-action shortcuts.

    On each call to :meth:`parse`, the user's input is matched against a
    prioritised list of patterns.  The first match wins.  If no pattern
    matches, ``None`` is returned and the input should be sent to the LLM.

    Example::

        parser = IntentParser()
        action = parser.parse("list files")
        # action.tool_name == "list_directory"
        # action.params == {"path": "."}
    """

    def __init__(self) -> None:
        self._patterns: List[_PatternEntry] = self._build_patterns()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, user_input: str) -> Optional[IntentAction]:
        """Try to match *user_input* against quick-action patterns.

        Args:
            user_input: Raw user input string (already stripped).

        Returns:
            An :class:`IntentAction` if a pattern matched, else ``None``.
        """
        if not user_input or not user_input.strip():
            return None

        text = user_input.strip()
        lowered = text.lower()

        # Fast-path: single-character shortcuts
        if lowered in ("q", "quit", "exit"):
            return IntentAction(tool_name="__quit__")
        if lowered in ("h", "help"):
            return IntentAction(tool_name="__help__")
        if lowered == "clear":
            return IntentAction(tool_name="__clear__")
        if lowered in ("history", "hist"):
            return IntentAction(tool_name="__history__")

        # Try each pattern in priority order
        for pattern, tool_name, extractor in self._patterns:
            match = pattern.match(text)
            if match:
                params = extractor(match)
                return IntentAction(tool_name=tool_name, params=params, confidence=1.0)

        return None

    # ------------------------------------------------------------------
    # Pattern definitions
    # ------------------------------------------------------------------

    @staticmethod
    def _build_patterns() -> List[_PatternEntry]:
        """Build the ordered list of (regex, tool_name, extractor) tuples."""
        patterns: List[_PatternEntry] = []

        # 1. Direct command execution: $ or ! prefix
        patterns.append((
            re.compile(r"^[\$!]\s*(?P<command>.+)$"),
            "run_command",
            lambda m: {"command": m.group("command").strip()},
        ))

        # 2. "run {command}" / "execute {command}"
        patterns.append((
            re.compile(r"^(?:run|exec|execute)\s+(?P<command>.+)$", re.IGNORECASE),
            "run_command",
            lambda m: {"command": m.group("command").strip()},
        ))

        # 3. "list files" / "ls" / "dir" — with optional path
        patterns.append((
            re.compile(
                r"^(?:list\s+files|ls|dir)\s*(?:(?:in|for|at)?\s*(?P<path>.+))?$",
                re.IGNORECASE,
            ),
            "list_directory",
            lambda m: {"path": m.group("path").strip() if m.group("path") else "."},
        ))

        # 4. "pwd" / "where am i" / "current directory" / "cd"
        patterns.append((
            re.compile(
                r"^(?:pwd|where\s+am\s+i|current\s+directory|cwd|cd\s*(?!-|\w))$",
                re.IGNORECASE,
            ),
            "list_directory",
            lambda m: {"path": "."},
        ))

        # 5. "disk usage" / "df" / "disk space" / "check disk"
        patterns.append((
            re.compile(
                r"^(?:disk\s+usage|df|disk\s+space|check\s+disk)\s*(?P<path>.*)$",
                re.IGNORECASE,
            ),
            "disk_usage",
            lambda m: {
                "path": m.group("path").strip() if m.group("path").strip() else None
            },
        ))

        # 6. "show memory" / "free memory" / "ram" / "memory info"
        patterns.append((
            re.compile(
                r"^(?:show\s+)?(?:free\s+)?(?:memory|mem|ram)\s*(?:info)?$",
                re.IGNORECASE,
            ),
            "memory_info",
            lambda m: {},
        ))

        # 7. "show cpu" / "cpu info" / "cpu"
        patterns.append((
            re.compile(r"^(?:show\s+)?cpu(?:\s+info)?$", re.IGNORECASE),
            "cpu_info",
            lambda m: {},
        ))

        # 8. "running processes" / "ps" / "top" / "processes"
        patterns.append((
            re.compile(
                r"^(?:running\s+)?process(?:es)?(?:\s+list)?|^ps$|^top$",
                re.IGNORECASE,
            ),
            "list_processes",
            lambda m: {},
        ))

        # 9. "git status"
        patterns.append((
            re.compile(r"^git\s+status\s*(?P<args>.*)$", re.IGNORECASE),
            "git_status",
            lambda m: {"args": m.group("args").strip()},
        ))

        # 10. "git log"
        patterns.append((
            re.compile(r"^git\s+log\s*(?P<args>.*)$", re.IGNORECASE),
            "run_command",
            lambda m: {"command": f"git log {m.group('args').strip()}"},
        ))

        # 11. "git diff"
        patterns.append((
            re.compile(r"^git\s+diff\s*(?P<args>.*)$", re.IGNORECASE),
            "run_command",
            lambda m: {"command": f"git diff {m.group('args').strip()}"},
        ))

        # 12. "find {pattern}" / "search for {pattern}" / "search {pattern}"
        patterns.append((
            re.compile(
                r"^(?:find|search\s+for?|grep(?:\s+-r)?)\s+(?P<pattern>.+)$",
                re.IGNORECASE,
            ),
            "search_files",
            lambda m: {"pattern": m.group("pattern").strip()},
        ))

        # 13. "what's using port {port}" / "port {port}" / "check port {port}"
        patterns.append((
            re.compile(
                r"(?:what'?s?\s+using\s+port|check\s+port|port)\s+(?P<port>\d+)",
                re.IGNORECASE,
            ),
            "port_check",
            lambda m: {"port": int(m.group("port"))},
        ))

        # 14. "show network" / "network info" / "ip addr" / "ifconfig"
        patterns.append((
            re.compile(
                r"^(?:show\s+)?network(?:\s+info)?|ip\s+addr|ifconfig$",
                re.IGNORECASE,
            ),
            "network_info",
            lambda m: {},
        ))

        # 15. "backup {file}" / "backup {file} to {dest}"
        patterns.append((
            re.compile(
                r"^backup\s+(?P<file>.+?)(?:\s+to\s+(?P<dest>.+))?$",
                re.IGNORECASE,
            ),
            "backup_file",
            lambda m: {
                "source": m.group("file").strip(),
                "destination": (
                    m.group("dest").strip()
                    if m.group("dest")
                    else m.group("file").strip() + ".bak"
                ),
            },
        ))

        # 16. "read {file}" / "show {file}" / "cat {file}" / "view {file}" / "edit {file}"
        patterns.append((
            re.compile(
                r"^(?:read|show|cat|view|open|edit|less)\s+(?P<file>.+)$",
                re.IGNORECASE,
            ),
            "read_file",
            lambda m: {"path": m.group("file").strip()},
        ))

        # 17. "whoami" / "who am i"
        patterns.append((
            re.compile(r"^who\s*ami$", re.IGNORECASE),
            "system_info",
            lambda m: {"detail": "user"},
        ))

        # 18. "system info" / "sysinfo" / "systeminfo"
        patterns.append((
            re.compile(r"^system\s*info|sysinfo|systeminfo$", re.IGNORECASE),
            "system_info",
            lambda m: {},
        ))

        # 19. "pip list" / "pip freeze" / "installed packages"
        patterns.append((
            re.compile(
                r"^pip\s+(?:list|freeze)|installed\s+packages|packages$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": "pip list --format=columns"},
        ))

        # 20. "tree" / "show tree" / "directory tree"
        patterns.append((
            re.compile(
                r"^(?:show\s+)?(?:dir(?:ectory)?)?\s*tree\s*(?P<path>.*)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {
                "command": (
                    f"tree {m.group('path').strip()}"
                    if m.group("path").strip()
                    else "tree -L 2"
                )
            },
        ))

        # 21. "mkdir {dir}" / "create directory {dir}" / "create folder {dir}"
        patterns.append((
            re.compile(
                r"^(?:mkdir|create\s+(?:dir(?:ectory)?|folder))\s+(?P<path>.+)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": f"mkdir -p {m.group('path').strip()}"},
        ))

        # 22. "touch {file}" / "create file {file}"
        patterns.append((
            re.compile(
                r"^(?:touch|create\s+file|new\s+file)\s+(?P<path>.+)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": f"touch {m.group('path').strip()}"},
        ))

        # 23. "copy {src} to {dest}" / "cp {src} {dest}"
        patterns.append((
            re.compile(
                r"^(?:copy|cp)\s+(?P<src>.+?)\s+to\s+(?P<dest>.+)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": f"cp -r {m.group('src').strip()} {m.group('dest').strip()}"},
        ))

        # 24. "move {src} to {dest}" / "mv {src} {dest}" / "rename {src} to {dest}"
        patterns.append((
            re.compile(
                r"^(?:move|mv|rename)\s+(?P<src>.+?)\s+to\s+(?P<dest>.+)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": f"mv {m.group('src').strip()} {m.group('dest').strip()}"},
        ))

        # 25. "rm {file}" / "remove {file}" / "delete {file}"
        patterns.append((
            re.compile(
                r"^(?:rm|remove|delete)\s+(?P<path>.+)$",
                re.IGNORECASE,
            ),
            "run_command",
            lambda m: {"command": f"rm {m.group('path').strip()}", "dangerous": True},
        ))

        return patterns
