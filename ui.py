""" 
Nexus — Interactive Terminal UI for setup and model selection.

Provides a keyboard-driven (arrow keys) terminal interface for:
- Selecting LLM backend (ollama, openai_compatible, mock)
- Choosing a model from available models
- First-run setup wizard
- In-session model switching

Uses only Python stdlib (curses/termios) — no external dependencies.

Developed under brutal-45.
"""

from __future__ import annotations

import os
import sys
import json
import subprocess
from typing import Any, Dict, List, Optional, Tuple


# ── ANSI escape helpers ──────────────────────────────────────────────────

class Ansi:
    """ANSI escape code constants for terminal UI rendering."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background
    BG_CYAN = "\033[46m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"

    # Cursor
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    MOVE_UP = "\033[A"
    MOVE_DOWN = "\033[B"
    MOVE_RIGHT = "\033[C"
    MOVE_LEFT = "\033[D"
    CLEAR_LINE = "\033[2K"
    CLEAR_SCREEN = "\033[2J\033[H"
    SAVE_POS = "\033[s"
    RESTORE_POS = "\033[u"


# ── Terminal input (raw mode) ────────────────────────────────────────────

def _read_key() -> str:
    """Read a single keypress from stdin without echo (raw mode).

    Returns:
        A string representing the key:
        - "up", "down", "left", "right" for arrow keys
        - "enter" for Return/Enter
        - "escape" for Escape
        - "tab" for Tab
        - "backspace" for Backspace/Delete
        - The literal character for printable keys
    """
    import tty
    import termios

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)

        if ch == "\x1b":  # ESC sequence
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                arrow_map = {"A": "up", "B": "down", "C": "right", "D": "left"}
                return arrow_map.get(ch3, f"esc_{ch3}")
            return "escape"

        if ch == "\r" or ch == "\n":
            return "enter"
        if ch == "\t":
            return "tab"
        if ch == "\x7f" or ch == "\x08":
            return "backspace"
        if ch == "\x03":  # Ctrl+C
            return "ctrl_c"
        if ch == "\x04":  # Ctrl+D
            return "ctrl_d"

        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_line(prompt: str = "") -> str:
    """Read a line of input with a prompt, with normal terminal settings."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


# ── Interactive picker ───────────────────────────────────────────────────

def pick(
    title: str,
    options: List[Dict[str, str]],
    selected: int = 0,
    subtitle: str = "",
) -> Optional[int]:
    """Interactive arrow-key picker for selecting an option.

    Args:
        title: Heading text for the picker.
        options: List of dicts with keys 'name' and 'description'.
        selected: Default selection index.
        subtitle: Optional text below the title.

    Returns:
        The index of the selected option, or None if cancelled (Esc/Ctrl+C).
    """
    if not options:
        return None

    selected = max(0, min(selected, len(options) - 1))
    scroll_offset = 0
    max_visible = min(len(options), 12)

    try:
        sys.stdout.write(Ansi.HIDE_CURSOR)

        while True:
            # Render
            sys.stdout.write(Ansi.CLEAR_SCREEN)
            _render_header(title, subtitle)

            # Calculate visible window
            if selected >= scroll_offset + max_visible:
                scroll_offset = selected - max_visible + 1
            elif selected < scroll_offset:
                scroll_offset = selected

            visible = options[scroll_offset:scroll_offset + max_visible]

            for i, opt in enumerate(visible):
                real_idx = scroll_offset + i
                is_selected = real_idx == selected

                name = opt.get("name", "")
                desc = opt.get("description", "")

                if is_selected:
                    # Highlighted row
                    line = f"  {Ansi.BG_CYAN}{Ansi.BLACK}{Ansi.BOLD} ❯ {name} "
                    if desc:
                        line += f" — {desc} "
                    line += " " * max(0, 40 - len(name) - len(desc))
                    line += Ansi.RESET
                else:
                    # Normal row
                    line = f"    {Ansi.BRIGHT_CYAN}{name}{Ansi.RESET}"
                    if desc:
                        line += f" {Ansi.DIM}— {desc}{Ansi.RESET}"

                sys.stdout.write(line + "\n")

            # Scroll indicators
            if scroll_offset > 0:
                sys.stdout.write(f"\n  {Ansi.DIM}↑ more above{Ansi.RESET}")
            if scroll_offset + max_visible < len(options):
                sys.stdout.write(f"\n  {Ansi.DIM}↓ more below{Ansi.RESET}")

            # Footer
            sys.stdout.write(f"\n\n  {Ansi.DIM}↑↓ navigate  Enter select  Esc cancel{Ansi.RESET}")
            sys.stdout.write(Ansi.CLEAR_LINE + "\n")
            sys.stdout.flush()

            # Handle input
            key = _read_key()
            if key == "up":
                selected = (selected - 1) % len(options)
            elif key == "down":
                selected = (selected + 1) % len(options)
            elif key == "enter":
                return selected
            elif key in ("escape", "ctrl_c", "ctrl_d"):
                return None
            elif key == "j":
                selected = (selected + 1) % len(options)
            elif key == "k":
                selected = (selected - 1) % len(options)
            elif key == "q":
                return None

    finally:
        sys.stdout.write(Ansi.SHOW_CURSOR)
        sys.stdout.flush()


def _render_header(title: str, subtitle: str = "") -> None:
    """Render the title bar for a picker screen."""
    width = _terminal_width()

    # Top border
    sys.stdout.write(f"{Ansi.BRIGHT_CYAN}{'━' * width}{Ansi.RESET}\n")

    # Title
    sys.stdout.write(f"\n  {Ansi.BOLD}{Ansi.BRIGHT_CYAN}{title}{Ansi.RESET}\n")

    if subtitle:
        sys.stdout.write(f"  {Ansi.DIM}{subtitle}{Ansi.RESET}\n")

    sys.stdout.write(f"\n{Ansi.DIM}{'─' * width}{Ansi.RESET}\n\n")


def _terminal_width() -> int:
    """Get terminal width, defaulting to 80."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


# ── Setup wizard ─────────────────────────────────────────────────────────

def run_setup_wizard(config) -> Optional[dict]:
    """Run the first-time setup wizard.

    Guides the user through:
    1. Selecting an LLM backend
    2. Selecting a model (auto-detects available models for ollama)
    3. Optional settings

    Args:
        config: The current NexusConfig instance.

    Returns:
        Dict with updated config values, or None if cancelled.
    """
    updates = {}

    # ── Step 1: Select backend ────────────────────────────────────────
    backend_options = [
        {"name": "ollama", "description": "Local LLM runner (recommended)"},
        {"name": "openai_compatible", "description": "Any OpenAI-compatible API server"},
        {"name": "mock", "description": "No LLM — tools only (for testing)"},
    ]

    # Default selection based on current config
    current_backend = getattr(config, "llm_backend", "ollama")
    default_idx = next(
        (i for i, o in enumerate(backend_options) if o["name"] == current_backend),
        0,
    )

    result = pick(
        title="Select LLM Backend",
        subtitle="Choose how Nexus connects to AI models on your machine.",
        options=backend_options,
        selected=default_idx,
    )

    if result is None:
        return None

    chosen_backend = backend_options[result]["name"]
    updates["llm_backend"] = chosen_backend

    # ── Step 2: Select model ──────────────────────────────────────────
    if chosen_backend == "ollama":
        models = _get_ollama_models()
        if models:
            model_options = [
                {"name": m, "description": "Installed locally"}
                for m in models
            ]
            model_options.append({"name": "Other...", "description": "Type a custom model name"})

            result = pick(
                title="Select Model",
                subtitle=f"Models available in ollama at {getattr(config, 'ollama_base_url', 'http://localhost:11434')}",
                options=model_options,
            )

            if result is None:
                return updates

            if model_options[result]["name"] == "Other...":
                custom = _read_line("  Enter model name: ")
                if custom:
                    updates["ollama_model"] = custom
            else:
                updates["ollama_model"] = model_options[result]["name"]
        else:
            # No models found — suggest pulling one
            sys.stdout.write(Ansi.CLEAR_SCREEN)
            _render_header(
                "No Models Found",
                "ollama is running but no models are installed yet.",
            )
            sys.stdout.write(f"  {Ansi.YELLOW}No models found in ollama.{Ansi.RESET}\n\n")
            sys.stdout.write(f"  Install a model with:\n")
            sys.stdout.write(f"    {Ansi.BRIGHT_CYAN}ollama pull llama3{Ansi.RESET}\n")
            sys.stdout.write(f"    {Ansi.BRIGHT_CYAN}ollama pull mistral{Ansi.RESET}\n")
            sys.stdout.write(f"    {Ansi.BRIGHT_CYAN}ollama pull codellama{Ansi.RESET}\n\n")

            custom = _read_line("  Or enter a model name (Enter to skip): ")
            if custom:
                updates["ollama_model"] = custom

    elif chosen_backend == "openai_compatible":
        sys.stdout.write(Ansi.CLEAR_SCREEN)
        _render_header(
            "OpenAI-Compatible Server Setup",
            "Connect to any server implementing the Chat Completions API.",
        )

        base_url = _read_line(
            f"  Server URL [{getattr(config, 'openai_base_url', 'http://localhost:8080/v1')}]: "
        )
        if base_url:
            updates["openai_base_url"] = base_url

        model_name = _read_line(
            f"  Model name [{getattr(config, 'openai_model', 'local-model')}]: "
        )
        if model_name:
            updates["openai_model"] = model_name

    # ── Step 3: Theme selection ───────────────────────────────────────
    theme_options = [
        {"name": "monokai", "description": "Dark with vibrant colors (default)"},
        {"name": "dark", "description": "Simple dark theme"},
        {"name": "dracula", "description": "Purple-tinted dark theme"},
        {"name": "light", "description": "Light background theme"},
    ]

    current_theme = getattr(config, "theme", "monokai")
    default_theme = next(
        (i for i, o in enumerate(theme_options) if o["name"] == current_theme),
        0,
    )

    result = pick(
        title="Select Theme",
        subtitle="Choose the terminal color scheme.",
        options=theme_options,
        selected=default_theme,
    )

    if result is not None:
        updates["theme"] = theme_options[result]["name"]

    return updates


def _get_ollama_models() -> List[str]:
    """Query ollama for locally installed models.

    Returns:
        List of model name strings, or empty list if ollama is not available.
    """
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []

        models = []
        for line in result.stdout.strip().split("\n"):
            # ollama list output: NAME  ID  SIZE  MODIFIED
            parts = line.split()
            if parts and parts[0] not in ("NAME", "name"):
                models.append(parts[0])

        return models
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return []


# ── In-session model switcher ────────────────────────────────────────────

def model_switcher(config) -> Optional[dict]:
    """Interactive model switcher for use during a session.

    Shows available models and lets the user switch without restarting.

    Args:
        config: The current NexusConfig instance.

    Returns:
        Dict with updated config values, or None if cancelled.
    """
    backend = getattr(config, "llm_backend", "ollama")

    if backend == "ollama":
        models = _get_ollama_models()
        current = getattr(config, "ollama_model", "llama3")

        if models:
            model_options = [{"name": m, "description": "Installed locally"} for m in models]
            model_options.append({"name": "Other...", "description": "Type a custom model name"})

            # Pre-select current model
            default_idx = next(
                (i for i, o in enumerate(model_options) if o["name"] == current),
                0,
            )

            result = pick(
                title="Switch Model",
                subtitle=f"Currently: {current}",
                options=model_options,
                selected=default_idx,
            )

            if result is None:
                return None

            if model_options[result]["name"] == "Other...":
                custom = _read_line("  Enter model name: ")
                if custom:
                    return {"ollama_model": custom}
            else:
                return {"ollama_model": model_options[result]["name"]}
        else:
            custom = _read_line("  No models found. Enter model name: ")
            if custom:
                return {"ollama_model": custom}

    elif backend == "openai_compatible":
        sys.stdout.write(Ansi.CLEAR_SCREEN)
        _render_header("Switch Model", f"Currently: {getattr(config, 'openai_model', 'local-model')}")

        model_name = _read_line("  New model name: ")
        if model_name:
            return {"openai_model": model_name}

    elif backend == "mock":
        # Allow switching to a real backend
        backend_options = [
            {"name": "ollama", "description": "Local LLM runner"},
            {"name": "openai_compatible", "description": "OpenAI-compatible API server"},
        ]
        result = pick(
            title="Switch Backend",
            subtitle="Currently: mock (no LLM)",
            options=backend_options,
        )
        if result is not None:
            updates = {"llm_backend": backend_options[result]["name"]}
            # Recursively get model for the new backend
            more = model_switcher(type('obj', (object,), updates)())
            if more:
                updates.update(more)
            return updates

    return None


# ── Config viewer ────────────────────────────────────────────────────────

def show_config(config) -> None:
    """Display the current configuration in a formatted view."""
    sys.stdout.write(Ansi.CLEAR_SCREEN)
    width = _terminal_width()

    _render_header("Configuration", "Current Nexus settings")

    # Group settings
    groups = [
        ("LLM Backend", [
            ("llm_backend", getattr(config, "llm_backend", "?")),
            ("ollama_base_url", getattr(config, "ollama_base_url", "?")),
            ("ollama_model", getattr(config, "ollama_model", "?")),
            ("openai_base_url", getattr(config, "openai_base_url", "?")),
            ("openai_model", getattr(config, "openai_model", "?")),
        ]),
        ("Generation", [
            ("temperature", str(getattr(config, "temperature", 0.7))),
            ("max_tokens", str(getattr(config, "max_tokens", 4096))),
            ("streaming", str(getattr(config, "streaming", True))),
        ]),
        ("Tools & Safety", [
            ("tool_calling_enabled", str(getattr(config, "tool_calling_enabled", True))),
            ("confirm_destructive", str(getattr(config, "confirm_destructive", True))),
            ("show_tool_calls", str(getattr(config, "show_tool_calls", True))),
            ("max_tool_calls_per_turn", str(getattr(config, "max_tool_calls_per_turn", 5))),
        ]),
        ("Display", [
            ("theme", getattr(config, "theme", "monokai")),
        ]),
    ]

    for group_name, settings in groups:
        sys.stdout.write(f"  {Ansi.BOLD}{Ansi.BRIGHT_CYAN}{group_name}{Ansi.RESET}\n")
        for key, val in settings:
            # Truncate long values
            display_val = val if len(val) < 50 else val[:47] + "..."
            sys.stdout.write(f"    {Ansi.DIM}{key:<28}{Ansi.RESET} {display_val}\n")
        sys.stdout.write("\n")

    sys.stdout.write(f"\n  {Ansi.DIM}Press any key to return...{Ansi.RESET}")
    sys.stdout.flush()
    _read_key()


# ── Welcome screen ──────────────────────────────────────────────────────

def show_welcome(config) -> bool:
    """Show a welcome/setup screen for first-time users.

    Returns True if the user completed setup, False if they skipped or cancelled.
    """
    # Check if this is first run
    config_path = os.path.expanduser(getattr(config, "config_file", "~/.nexus/config.json"))
    is_first_run = not os.path.isfile(config_path)

    if not is_first_run:
        return False  # Not first run, skip wizard

    sys.stdout.write(Ansi.CLEAR_SCREEN)
    width = _terminal_width()

    # Animated title
    banner_lines = [
        "",
        f"  {Ansi.BRIGHT_CYAN}{Ansi.BOLD}Welcome to Nexus!{Ansi.RESET}",
        "",
        f"  {Ansi.DIM}Your local AI terminal assistant.{Ansi.RESET}",
        f"  {Ansi.DIM}Let's get you set up in just a few steps.{Ansi.RESET}",
        "",
    ]

    for line in banner_lines:
        sys.stdout.write(line + "\n")
    sys.stdout.flush()

    # Ask if they want to run setup
    setup_options = [
        {"name": "Yes, run setup", "description": "Choose backend, model, and theme"},
        {"name": "Skip for now", "description": "Use defaults (ollama + llama3 + monokai)"},
    ]

    result = pick(
        title="",
        subtitle="",
        options=setup_options,
    )

    if result is None or result == 1:
        return False

    # Run the setup wizard
    updates = run_setup_wizard(config)
    if updates:
        # Apply updates to config
        for key, value in updates.items():
            setattr(config, key, value)

        # Save config
        try:
            from nexus.config import save_config
            save_config(config)
        except Exception:
            pass

    return True
