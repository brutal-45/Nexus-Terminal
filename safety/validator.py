"""Safety validator — the gatekeeper for all tool executions.
 
Every tool call in Nexus **must** pass through :class:`SafetyValidator`
before it is handed to the executor.  This is the single, centralised
enforcement point for all safety rules.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from nexus.safety.rules import SafetyRules, DangerousPattern

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

# Tools that are considered harmless and can bypass pattern checks.
DEFAULT_ALLOWLIST: Set[str] = {
    "read_file",
    "list_directory",
    "search_files",
    "get_file_info",
    "web_search",
    "list_tools",
    "help",
}

# Tools that are never allowed regardless of arguments.
DEFAULT_BLOCKLIST: Set[str] = set()

# TTL (seconds) for a user-confirmed dangerous operation so the same
# operation isn't re-prompted in quick succession.
_CONFIRMATION_TTL = 300  # 5 minutes

# Maximum input length accepted before silent truncation.
_MAX_INPUT_LENGTH = 100_000

# Configuration-file path heuristics (used for write warnings).
_CONFIG_PATH_FRAGMENTS: List[str] = [
    "/.bashrc",
    "/.zshrc",
    "/.profile",
    "/.bash_profile",
    "/.bash_logout",
    "/.ssh/",
    "/etc/",
    "docker-compose",
    "Dockerfile",
    ".env",
    "config.yaml",
    "config.yml",
    "config.json",
    "config.toml",
    "settings.json",
    "preferences.json",
]


# ---------------------------------------------------------------------------
#  SafetyValidator
# ---------------------------------------------------------------------------

class SafetyValidator:
    """Validates tool calls and commands before execution.

    Usage::

        validator = SafetyValidator()
        ok, msg = validator.validate_tool_call("run_command", {"command": "ls"})
        if not ok:
            print(f"Blocked: {msg}")

    The validator delegates the actual pattern matching to :class:`SafetyRules`
    while adding allow/block-list management, confirmation tracking, input
    sanitisation, and audit logging on top.
    """

    def __init__(
        self,
        *,
        config: Optional[Dict[str, Any]] = None,
        rules: Optional[SafetyRules] = None,
        allowlist: Optional[Set[str]] = None,
        blocklist: Optional[Set[str]] = None,
    ) -> None:
        self.config: Dict[str, Any] = config or {}

        # Rule engine
        self.rules: SafetyRules = rules or SafetyRules()

        # Allow / block lists
        self._allowlist: Set[str] = set(allowlist or DEFAULT_ALLOWLIST)
        self._blocklist: Set[str] = set(blocklist or DEFAULT_BLOCKLIST)

        # Confirmed dangerous operations: fingerprint → expiry timestamp
        self._confirmed: Dict[str, float] = {}

        # Operations that were warned about (for deduplication)
        self._warned: Set[str] = set()

        # Audit log entries (in-memory ring buffer)
        self._audit_buffer: List[Dict[str, Any]] = []
        self._audit_buffer_size: int = 500
        if isinstance(self.config, dict):
            self._audit_buffer_size = self.config.get("audit_buffer_size", 500)

    # ------------------------------------------------------------------
    #  Public API – validation
    # ------------------------------------------------------------------

    def validate_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Validate a tool call.

        Returns:
            ``(is_safe, message)``.  When *is_safe* is ``False`` the caller
            must refuse to execute the tool.  When *is_safe* is ``True`` the
            optional *message* can be displayed as a non-blocking warning.
        """
        # 1. Blocklist – hard block
        if tool_name in self._blocklist:
            reason = f"Tool '{tool_name}' is blocked by administrator."
            self._audit(tool_name, arguments, blocked=True, reason=reason)
            return False, reason

        # 2. Allowlist – fast path, always safe
        if tool_name in self._allowlist:
            self._audit(tool_name, arguments, blocked=False)
            return True, ""

        # 3. Confirmation cache – skip re-check if recently confirmed
        fingerprint = self._fingerprint(tool_name, arguments)
        if fingerprint in self._confirmed:
            if self._confirmed[fingerprint] > time.monotonic():
                self._audit(tool_name, arguments, blocked=False, reason="confirmation_cached")
                return True, ""
            else:
                del self._confirmed[fingerprint]  # expired

        # 4. Delegate to rule engine
        is_safe, message = self.rules.check_tool_call(tool_name, arguments)

        if not is_safe:
            self._audit(tool_name, arguments, blocked=True, reason=message)
            return False, message

        # 5. Warning pass (non-blocking)
        warning = self._check_for_warnings(tool_name, arguments)
        self._audit(tool_name, arguments, blocked=False, reason=warning or "")
        return True, warning

    def is_destructive(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Return ``True`` if the tool call is considered destructive.

        Destructive operations should require explicit user confirmation
        before execution (e.g. via a ``y/N`` prompt).
        """
        # Shell commands – delegate to rules
        if tool_name == "run_command":
            cmd = arguments.get("command", "")
            return self.rules.is_destructive(cmd)

        # File-level destructive tools
        destructive_tools = {
            "delete_file",
            "move_file",
            "rename_file",
            "compress_files",
        }
        if tool_name in destructive_tools:
            path = self._extract_path(arguments)
            if path and os.path.exists(path):
                return True

        # Write to an existing file is also destructive (overwrite)
        if tool_name == "write_file":
            path = arguments.get("path", "")
            if path and os.path.isfile(path):
                return True

        # Git mutations
        if tool_name in {"git_commit", "git_push", "git_reset", "git_force_push", "git_rebase"}:
            return True

        return False

    def confirm_destructive(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        ttl: Optional[float] = None,
    ) -> None:
        """Mark a destructive operation as user-confirmed for *ttl* seconds."""
        fingerprint = self._fingerprint(tool_name, arguments)
        self._confirmed[fingerprint] = time.monotonic() + (ttl or _CONFIRMATION_TTL)
        logger.debug("Confirmed destructive operation %s (tool=%s)", fingerprint, tool_name)

    # ------------------------------------------------------------------
    #  Public API – allow / block list management
    # ------------------------------------------------------------------

    def add_to_allowlist(self, tool_name: str) -> None:
        """Add a tool to the allowlist (always allowed)."""
        self._allowlist.add(tool_name)
        self._blocklist.discard(tool_name)
        logger.info("Tool %s added to allowlist", tool_name)

    def remove_from_allowlist(self, tool_name: str) -> None:
        """Remove a tool from the allowlist."""
        self._allowlist.discard(tool_name)
        logger.info("Tool %s removed from allowlist", tool_name)

    def add_to_blocklist(self, tool_name: str) -> None:
        """Add a tool to the blocklist (always blocked)."""
        self._blocklist.add(tool_name)
        self._allowlist.discard(tool_name)
        logger.info("Tool %s added to blocklist", tool_name)

    def remove_from_blocklist(self, tool_name: str) -> None:
        """Remove a tool from the blocklist."""
        self._blocklist.discard(tool_name)
        logger.info("Tool %s removed from blocklist", tool_name)

    # ------------------------------------------------------------------
    #  Public API – convenience methods
    # ------------------------------------------------------------------

    def check_command(self, command: str) -> Tuple[bool, str, str]:
        """Check a raw shell command.

        Returns:
            ``(is_safe, reason, severity)``.
        """
        return self.rules.check_command(command)

    def check_file_write(self, path: str, content: str = "") -> Tuple[bool, str]:
        """Check whether writing to *path* with *content* is safe.

        Returns ``(is_safe, warning_message)``.
        """
        safe, reason = self.rules.check_path(path)
        if not safe:
            return False, reason

        if not content:
            return True, ""

        # Warn about configuration files
        resolved = str(Path(path).resolve())
        for fragment in _CONFIG_PATH_FRAGMENTS:
            if fragment in resolved:
                return True, f"Warning: You are modifying a configuration file: {path}"

        return True, ""

    def sanitize_input(self, user_input: str) -> str:
        """Sanitize user input to prevent injection attacks.

        * Strips null bytes.
        * Truncates excessively long input.
        """
        sanitized = user_input.replace("\x00", "")
        if len(sanitized) > _MAX_INPUT_LENGTH:
            sanitized = sanitized[:_MAX_INPUT_LENGTH] + "\n... (input truncated)"
        return sanitized

    # ------------------------------------------------------------------
    #  Audit logging
    # ------------------------------------------------------------------

    def _audit(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        blocked: bool,
        reason: str = "",
    ) -> None:
        """Record an audit entry in the in-memory ring buffer."""
        # Avoid storing large content blobs
        safe_args = {k: v for k, v in arguments.items() if k not in ("content", "data")}
        entry = {
            "timestamp": time.time(),
            "status": "BLOCKED" if blocked else "OK",
            "tool": tool_name,
            "args": safe_args,
            "reason": reason,
        }
        self._audit_buffer.append(entry)

        # Trim the ring buffer
        if len(self._audit_buffer) > self._audit_buffer_size:
            self._audit_buffer = self._audit_buffer[-self._audit_buffer_size :]

        # Also emit via the logging framework
        level = logging.WARNING if blocked else logging.DEBUG
        logger.log(
            level,
            "Safety audit %s: tool=%s reason=%s",
            entry["status"],
            tool_name,
            reason,
        )

    def get_audit_log(self, *, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return the recent audit log entries.

        Args:
            last_n: If given, return only the most recent *last_n* entries.
        """
        if last_n is not None:
            return self._audit_buffer[-last_n:]
        return list(self._audit_buffer)

    def clear_audit_log(self) -> None:
        """Clear all buffered audit entries."""
        self._audit_buffer.clear()

    # ------------------------------------------------------------------
    #  Warnings (non-blocking)
    # ------------------------------------------------------------------

    def _check_for_warnings(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Return a non-empty warning string if the call deserves a warning."""
        if tool_name == "write_file":
            path = arguments.get("path", "")
            _, warning = self.check_file_write(path, arguments.get("content", ""))
            return warning

        if tool_name in {"git_push", "git_force_push"}:
            return "Warning: You are pushing to a remote repository."

        return ""

    # ------------------------------------------------------------------
    #  Fingerprinting (for confirmation dedup)
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(tool_name: str, arguments: Dict[str, Any]) -> str:
        """Create a deterministic fingerprint for a tool call."""
        # Normalise argument keys for consistent hashing
        normalised = {k: arguments[k] for k in sorted(arguments)}
        raw = f"{tool_name}:{normalised}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    #  Path extraction helper
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_path(arguments: Dict[str, Any]) -> Optional[str]:
        """Pull the most likely file-system path from an arguments dict."""
        for key in ("path", "source", "destination", "file", "filepath"):
            val = arguments.get(key)
            if isinstance(val, str) and val:
                return val
        # Handle list-of-paths
        paths = arguments.get("paths")
        if isinstance(paths, list) and paths:
            return str(paths[0])
        return None

    # ------------------------------------------------------------------
    #  Safety report / diagnostics
    # ------------------------------------------------------------------

    def get_safety_report(self) -> Dict[str, Any]:
        """Return a summary of the current safety configuration.

        Useful for ``/status`` commands and debugging.
        """
        return {
            "allowlisted_tools": sorted(self._allowlist),
            "blocklisted_tools": sorted(self._blocklist),
            "dangerous_patterns_count": len(self.rules.dangerous_patterns),
            "sensitive_patterns_count": len(self.rules.sensitive_patterns),
            "blocked_paths": list(self.rules.blocked_paths),
            "protected_processes": list(self.rules.protected_processes),
            "pending_confirmations": len(self._confirmed),
            "audit_entries": len(self._audit_buffer),
        }

    def list_dangerous_commands(self) -> List[str]:
        """Proxy for :meth:`SafetyRules.get_dangerous_commands_list`."""
        return self.rules.get_dangerous_commands_list()

    def list_sensitive_patterns(self) -> List[str]:
        """Proxy for :meth:`SafetyRules.get_sensitive_commands_list`."""
        return self.rules.get_sensitive_commands_list()
