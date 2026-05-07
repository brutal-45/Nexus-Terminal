"""Terminal display system for Nexus.

Provides rich terminal output with markdown rendering, syntax highlighting,
tables, and colour theming.  Gracefully falls back to plain ANSI output when
the `rich` package is not installed.
"""

from __future__ import annotations

import os
import sys
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional


class Display:
    """Terminal display manager. Uses Rich if available, falls back to ANSI codes.

    Args:
        config: Optional config object.  Expected attribute: ``theme`` (str).
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        self.config = config
        self._use_rich = self._check_rich()
        self._colors = self._get_colors()
        self._width = self._get_terminal_width()

    # ------------------------------------------------------------------
    # Rich detection
    # ------------------------------------------------------------------

    def _check_rich(self) -> bool:
        """Return True if the Rich library is importable."""
        try:
            import rich  # noqa: F401
            import rich.console  # noqa: F401
            import rich.markdown  # noqa: F401
            import rich.syntax  # noqa: F401
            import rich.table  # noqa: F401
            import rich.panel  # noqa: F401

            from rich.console import Console

            self._console = Console()
            self._rich = True
            return True
        except ImportError:
            self._rich = False
            return False

    # ------------------------------------------------------------------
    # Terminal helpers
    # ------------------------------------------------------------------

    def _get_terminal_width(self) -> int:
        """Get the current terminal width, defaulting to 80."""
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80

    @staticmethod
    def _supports_color() -> bool:
        """Check whether the terminal supports colour output."""
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM") in ("dumb", ""):
            return False
        if not sys.stdout.isatty() and not sys.stderr.isatty():
            # Allow colour in CI environments
            if not os.environ.get("CI") and not os.environ.get("GITHUB_ACTIONS"):
                return False
        return True

    def _get_colors(self) -> Dict[str, str]:
        """Return the ANSI colour map for the active theme."""
        reset = "\033[0m"
        bold = "\033[1m"
        dim = "\033[2m"

        if not self._supports_color():
            return {
                "primary": "", "success": "", "warning": "", "error": "",
                "info": "", "code": "", "tool": "", "dim": "", "bold": "",
                "reset": "", "user": "", "assistant": "", "heading": "",
                "muted": "", "border": "",
            }

        themes: Dict[str, Dict[str, str]] = {
            "monokai": {
                "primary": "\033[38;5;81m",
                "success": "\033[38;5;76m",
                "warning": "\033[38;5;220m",
                "error": "\033[38;5;196m",
                "info": "\033[38;5;147m",
                "code": "\033[38;5;116m",
                "tool": "\033[38;5;208m",
                "dim": "\033[38;5;243m",
                "bold": bold,
                "reset": reset,
                "user": "\033[38;5;81m",
                "assistant": "\033[38;5;186m",
                "heading": "\033[38;5;229m",
                "muted": "\033[38;5;246m",
                "border": "\033[38;5;240m",
            },
            "dark": {
                "primary": "\033[36m",
                "success": "\033[32m",
                "warning": "\033[33m",
                "error": "\033[31m",
                "info": "\033[35m",
                "code": "\033[32m",
                "tool": "\033[33m",
                "dim": "\033[90m",
                "bold": bold,
                "reset": reset,
                "user": "\033[36m",
                "assistant": "\033[37m",
                "heading": "\033[33m",
                "muted": "\033[90m",
                "border": "\033[90m",
            },
            "light": {
                "primary": "\033[34m",
                "success": "\033[32m",
                "warning": "\033[33m",
                "error": "\033[31m",
                "info": "\033[35m",
                "code": "\033[32m",
                "tool": "\033[33m",
                "dim": "\033[90m",
                "bold": bold,
                "reset": reset,
                "user": "\033[34m",
                "assistant": "\033[30m",
                "heading": "\033[34m",
                "muted": "\033[90m",
                "border": "\033[90m",
            },
        }

        theme_name = "monokai"
        if self.config:
            theme_name = getattr(self.config, "theme", "monokai") or "monokai"
        return themes.get(theme_name, themes["monokai"])

    def c(self, text: str, color_key: str) -> str:
        """Colour *text* using the ANSI code for *color_key*.

        If *text* is empty, returns an empty string (avoids stray reset codes).
        """
        if not text:
            return ""
        c = self._colors
        prefix = c.get(color_key, c["reset"])
        return f"{prefix}{text}{c['reset']}"

    # ------------------------------------------------------------------
    # Welcome banner
    # ------------------------------------------------------------------

    BANNER = r"""
  ██╗      █████╗ ██╗  ██╗███████╗██╗   ██╗████████╗
  ██║     ██╔══██╗╚██╗██╔╝██╔════╝╚██╗ ██╔╝╚══██╔══╝
  ██║     ███████║ ╚███╔╝ █████╗   ╚████╔╝    ██║
  ██║     ██╔══██║ ██╔██╗ ██╔══╝    ╚██╔╝     ██║
  ███████╗██║  ██║██╔╝ ██╗███████╗   ██║      ██║
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝      ╚═╝"""

    def welcome(self, workspace_info: Dict[str, Any], config: Optional[Any] = None) -> None:
        """Display the welcome banner with system information."""
        self.clear()

        if self._use_rich:
            from rich.panel import Panel
            from rich.text import Text

            banner_text = Text(self.BANNER.strip("\n"), style="bold cyan")
            self._console.print(banner_text)
        else:
            print(self.c(self.BANNER.strip("\n"), "primary"))

        self.divider("═")

        # System info line
        ws = workspace_info or {}
        parts: List[str] = []
        parts.append(f"OS: {ws.get('os', 'unknown')}")
        parts.append(f"Kernel: {ws.get('kernel', 'unknown')}")
        parts.append(f"Arch: {ws.get('arch', 'unknown')}")
        parts.append(f"Python: {ws.get('python_version', 'unknown')}")
        parts.append(f"Shell: {ws.get('shell', 'unknown')}")

        if self._use_rich:
            from rich.text import Text
            info_text = Text("  ".join(parts), style="dim")
            self._console.print(info_text)
        else:
            print(self.c("  ".join(parts), "dim"))

        # Working directory & project
        cwd = ws.get("cwd", ".")
        project = ws.get("project_name", "")
        project_type = ws.get("project_type", "")
        loc = f"{cwd}"
        if project:
            loc += f"  ({project}"
            if project_type:
                loc += f" — {project_type}"
            loc += ")"

        if self._use_rich:
            from rich.text import Text
            self._console.print(Text(f"  📂 {loc}", style="bold cyan"))
        else:
            print(self.c(f"  📂 {loc}", "primary"))

        # Model info
        if config:
            model = getattr(config, "model_name", None)
            provider = getattr(config, "provider", None)
            if model:
                model_str = f"  🧠 Model: {model}"
                if provider:
                    model_str += f" ({provider})"
                if self._use_rich:
                    from rich.text import Text
                    self._console.print(Text(model_str, style="dim"))
                else:
                    print(self.c(model_str, "dim"))

        self.divider("═")

        print()
        print(self.c("  Welcome to Nexus. Type your question or command.", "primary"))
        print(self.c("  Type", "dim") + " " + self.c("help", "bold") + " " + self.c("for available commands, or", "dim") + " " + self.c("quit", "bold") + " " + self.c("to exit.", "dim"))
        print()

    # ------------------------------------------------------------------
    # Prompt & input
    # ------------------------------------------------------------------

    def prompt(self) -> str:
        """Show the input prompt and return the user's input."""
        prompt_str = self.c("❯ ", "primary")
        try:
            return input(prompt_str)
        except (EOFError, KeyboardInterrupt):
            print()  # newline after ^C/^D
            return ""

    # ------------------------------------------------------------------
    # Assistant output
    # ------------------------------------------------------------------

    def assistant(self, text: str) -> None:
        """Display an assistant response, with Markdown rendering if Rich is available."""
        if not text:
            return

        if self._use_rich:
            from rich.markdown import Markdown
            self._console.print(Markdown(text))
        else:
            # Plain-text fallback — clean up markdown formatting
            cleaned = self._strip_markdown(text)
            wrapped = textwrap.fill(cleaned, width=self._width - 2, replace_whitespace=False)
            print(wrapped)

    def user_echo(self, text: str) -> None:
        """Echo back what the user typed."""
        prefix = self.c("You", "bold")
        print(f"{prefix}: {text}")

    # ------------------------------------------------------------------
    # Status messages
    # ------------------------------------------------------------------

    def info(self, text: str) -> None:
        """Display an informational message."""
        print(self.c(f"ℹ {text}", "info"))

    def success(self, text: str) -> None:
        """Display a success message."""
        print(self.c(f"✓ {text}", "success"))

    def warning(self, text: str) -> None:
        """Display a warning message."""
        print(self.c(f"⚠ {text}", "warning"), file=sys.stderr)

    def error(self, text: str) -> None:
        """Display an error message."""
        print(self.c(f"✗ {text}", "error"), file=sys.stderr)

    # ------------------------------------------------------------------
    # Code display
    # ------------------------------------------------------------------

    def code(self, code: str, language: str = "") -> None:
        """Display a fenced code block with syntax highlighting if Rich is available."""
        if not code:
            return

        if self._use_rich and language:
            from rich.syntax import Syntax

            try:
                syntax = Syntax(code, language, theme="monokai", line_numbers=False, word_wrap=True)
                self._console.print(syntax)
                return
            except Exception:
                pass  # Fall through to plain display

        # Fallback: plain code block
        if language:
            print(self.c(f"```{language}", "dim"))
        else:
            print(self.c("```", "dim"))
        print(code)
        print(self.c("```", "dim"))

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    def table(
        self,
        headers: List[str],
        rows: List[List[str]],
        title: str = "",
    ) -> None:
        """Display a table. Uses Rich if available, otherwise ASCII fallback."""
        if self._use_rich:
            from rich.table import Table

            t = Table(title=title or None, show_lines=False, header_style="bold cyan")
            for h in headers:
                t.add_column(h)
            for row in rows:
                t.add_row(*row)
            self._console.print(t)
        else:
            self._plain_table(headers, rows, title)

    def _plain_table(self, headers: List[str], rows: List[List[str]], title: str = "") -> None:
        """Render a simple ASCII table."""
        if title:
            print(self.c(title, "bold"))
            print()

        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(cell))

        # Build separator
        sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"

        # Header
        header_cells = [f" {h:<{col_widths[i]}} " for i, h in enumerate(headers)]
        print(sep)
        print(self.c("|" + "|".join(header_cells) + "|", "bold"))

        # Rows
        print(self.c(sep, "border"))
        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                w = col_widths[i] if i < len(col_widths) else len(cell)
                cells.append(f" {cell:<{w}} ")
            print("|" + "|".join(cells) + "|")

        print(self.c(sep, "border"))

    # ------------------------------------------------------------------
    # Tool display
    # ------------------------------------------------------------------

    def tool_call(self, tool_name: str, args: Dict[str, Any]) -> None:
        """Display a tool-call notification."""
        args_str = self._format_args(args)
        if self._use_rich:
            from rich.panel import Panel
            from rich.text import Text

            label = Text(f"⚙  {tool_name}", style="bold orange3")
            detail = Text(f"    {args_str}", style="dim")
            panel = Panel(detail, title=label, border_style="orange3", padding=(0, 1))
            self._console.print(panel)
        else:
            print()
            print(self.c(f"  ⚙ {tool_name}", "tool"))
            if args_str:
                for line in args_str.split("\n"):
                    print(self.c(f"    {line}", "dim"))
            print()

    def show_result(self, result: Dict[str, Any]) -> None:
        """Display a tool execution result.

        Expected keys in *result*:
        - ``success`` (bool)
        - ``output`` (str)
        - ``error`` (str, optional)
        - ``files_changed`` (list[str], optional)
        """
        success = result.get("success", False)
        output = result.get("output", "")
        error = result.get("error", "")
        files_changed = result.get("files_changed", [])

        if success:
            self.success("Tool executed successfully")
        else:
            self.error("Tool execution failed")

        if error:
            print(self.c(f"  Error: {error}", "error"))

        if output:
            # Truncate very long output
            lines = output.splitlines()
            max_lines = 50
            if len(lines) > max_lines:
                display_output = "\n".join(lines[:max_lines])
                display_output += f"\n… ({len(lines) - max_lines} more lines)"
            else:
                display_output = output

            if self._use_rich and len(display_output.strip().splitlines()) <= 20:
                from rich.panel import Panel
                self._console.print(Panel(display_output.strip(), border_style="dim", padding=(0, 1)))
            else:
                for line in display_output.splitlines():
                    print(self.c(f"  {line}", "dim"))

        if files_changed:
            for f in files_changed:
                self.info(f"  Changed: {f}")

    # ------------------------------------------------------------------
    # Confirmation & progress
    # ------------------------------------------------------------------

    def confirm(self, message: str) -> bool:
        """Ask for user confirmation. Returns True if confirmed."""
        print(self.c(f"⚠ {message}", "warning"))
        try:
            response = input(self.c("[y/N] ", "warning")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return response in ("y", "yes")

    def progress(self, message: str) -> None:
        """Show a progress indicator (overwrites current line)."""
        print(self.c(f"⟳ {message}", "dim"), end="\r", flush=True)

    def progress_done(self, message: str = "Done") -> None:
        """Clear the progress line and show completion."""
        # Overwrite the progress line with spaces
        blank = " " * (self._width - 1)
        print(f"\r{blank}\r", end="")
        print(self.c(f"✓ {message}", "success"))

    # ------------------------------------------------------------------
    # Miscellaneous
    # ------------------------------------------------------------------

    def goodbye(self) -> None:
        """Display a goodbye message."""
        print()
        print(self.c("Goodbye! Session ended. Come back anytime.", "primary"))
        print()

    def clear(self) -> None:
        """Clear the terminal screen."""
        print("\033[2J\033[H", end="", flush=True)

    def divider(self, char: str = "─", width: Optional[int] = None) -> None:
        """Print a horizontal divider line."""
        w = width or self._width
        print(self.c(char * w, "dim"))

    def heading(self, text: str, level: int = 1) -> None:
        """Print a heading. Level 1 = large, level 2 = medium, level 3 = small."""
        if level == 1:
            line = f"\n{text}\n{'=' * len(text)}"
            print(self.c(line, "heading"))
        elif level == 2:
            line = f"\n{text}\n{'-' * len(text)}"
            print(self.c(line, "primary"))
        else:
            print(self.c(f"\n{text}", "bold"))

    def bullet(self, text: str, indent: int = 2) -> None:
        """Print a bullet point."""
        prefix = " " * indent + "• "
        print(self.c(prefix, "primary") + text)

    def numbered(self, number: int, text: str, indent: int = 2) -> None:
        """Print a numbered item."""
        prefix = " " * indent + f"{number}. "
        print(self.c(prefix, "primary") + text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove common Markdown formatting for plain-text display."""
        import re

        # Remove code fences
        cleaned = re.sub(r"```[\w]*\n?", "", text)
        # Remove inline code
        cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
        # Remove bold/italic
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)
        cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)
        cleaned = re.sub(r"_(.+?)_", r"\1", cleaned)
        # Remove heading markers
        cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
        # Remove links, keep text
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        # Remove horizontal rules
        cleaned = re.sub(r"^---+$", "─" * 40, cleaned, flags=re.MULTILINE)
        return cleaned

    @staticmethod
    def _format_args(args: Dict[str, Any], indent: int = 0) -> str:
        """Format tool-call arguments as a readable string."""
        if not args:
            return ""

        lines: List[str] = []
        for k, v in args.items():
            if isinstance(v, (dict, list)):
                import json
                lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            elif isinstance(v, str) and len(v) > 80:
                lines.append(f"{k}: {v[:77]}…")
            else:
                lines.append(f"{k}: {v}")

        prefix = " " * indent
        return ("\n" + prefix).join(lines)
