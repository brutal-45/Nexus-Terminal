"""
Nexus Configuration Module.

Manages all configuration options for the Nexus assistant, including:
- LLM backend settings (ollama, openai_compatible, mock)
- Tool calling parameters
- Display and theme preferences
- Safety and validation settings
- Session and history management
- Workspace detection options

Configuration is loaded from JSON files, with sensible defaults for all values.
Paths are automatically expanded and resolved using pathlib.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class NexusConfig:
    """Comprehensive configuration for Nexus.

    All settings have sensible defaults that work out of the box with
    a local ollama installation. Override via JSON config file or CLI flags.

    Attributes:
        llm_backend: LLM backend to use. One of "ollama", "openai_compatible", "mock".
        ollama_base_url: Base URL for the ollama API server.
        ollama_model: Default model name for ollama.
        openai_base_url: Base URL for openai-compatible API servers.
        openai_model: Default model name for openai-compatible backends.
        openai_api_key: API key for openai-compatible endpoints (often unused locally).
        temperature: Sampling temperature for LLM responses (0.0 - 2.0).
        max_tokens: Maximum number of tokens to generate per response.
        context_window: Maximum context window size in tokens for the conversation.
        max_history_turns: Maximum number of conversation turns to retain.
        max_tool_calls_per_turn: Maximum sequential tool calls per user turn.
        tool_calling_enabled: Whether to enable function/tool calling.
        streaming: Whether to stream LLM responses token-by-token.
        theme: Terminal color theme. One of "monokai", "solarized_dark", "github_dark", "dracula".
        show_tool_calls: Whether to display tool call details in the terminal.
        confirm_destructive: Whether to prompt before executing destructive commands.
        dangerous_commands: List of command patterns considered dangerous.
        max_command_output_chars: Maximum characters to display from command output.
        command_timeout: Timeout in seconds for shell command execution.
        working_directory: Working directory for file/shell operations.
        history_file: Path to conversation history JSON file.
        config_file: Path to the main configuration JSON file.
        auto_workspace_detect: Whether to auto-detect project workspace metadata.
        session_name: Optional name for the current session.
    """

    # ── LLM Backend Settings ──────────────────────────────────────────────
    llm_backend: str = "ollama"  # choices: "ollama", "openai_compatible", "mock"

    # ── ollama Settings ───────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # ── openai-compatible Settings ────────────────────────────────────────
    openai_base_url: str = "http://localhost:8080/v1"
    openai_model: str = "local-model"
    openai_api_key: str = "not-needed"

    # ── Generation Parameters ─────────────────────────────────────────────
    temperature: float = 0.7
    max_tokens: int = 4096
    context_window: int = 8192

    # ── Conversation Management ───────────────────────────────────────────
    max_history_turns: int = 50
    max_tool_calls_per_turn: int = 5

    # ── Tool Calling ──────────────────────────────────────────────────────
    tool_calling_enabled: bool = True

    # ── Display Settings ──────────────────────────────────────────────────
    streaming: bool = True
    theme: str = "monokai"  # choices: "monokai", "solarized_dark", "github_dark", "dracula"
    show_tool_calls: bool = True

    # ── Safety Settings ───────────────────────────────────────────────────
    confirm_destructive: bool = True
    dangerous_commands: List[str] = field(default_factory=lambda: [
        "rm -rf",
        "DROP TABLE",
        "chmod 777",
        "mkfs",
        "dd if=",
        "> /dev/sd",
        "format ",
        ":(){ :|:& };:",
    ])
    max_command_output_chars: int = 10000
    command_timeout: int = 30

    # ── File System Settings ──────────────────────────────────────────────
    working_directory: str = "."

    # ── Persistence Settings ──────────────────────────────────────────────
    history_file: str = "~/.nexus/history.json"
    config_file: str = "~/.nexus/config.json"

    # ── Workspace Settings ────────────────────────────────────────────────
    auto_workspace_detect: bool = True
    session_name: Optional[str] = None


def _expand_path(path: str) -> str:
    """Expand user home directory and resolve the path to an absolute path.

    Args:
        path: A file path string that may contain ~ or relative components.

    Returns:
        Fully resolved absolute path string.
    """
    expanded = os.path.expanduser(path)
    return os.path.abspath(expanded)


def _resolve_config_paths(config: NexusConfig) -> NexusConfig:
    """Resolve all path fields in the config to absolute paths.

    This mutates the config in place and returns it for convenience.
    Only known path fields are resolved; all other fields are left unchanged.

    Args:
        config: A NexusConfig instance with potentially relative path fields.

    Returns:
        The same config instance with resolved path fields.
    """
    from pathlib import Path

    # Resolve working directory first so it can serve as base for relative paths
    if config.working_directory:
        config.working_directory = str(Path(config.working_directory).expanduser().resolve())

    # Resolve history file path
    if config.history_file:
        config.history_file = str(Path(config.history_file).expanduser())

    # Resolve config file path
    if config.config_file:
        config.config_file = str(Path(config.config_file).expanduser())

    return config


def get_default_config() -> NexusConfig:
    """Create and return a NexusConfig with all default values.

    Path fields are automatically expanded and resolved.

    Returns:
        A fully initialized NexusConfig with sensible defaults.
    """
    config = NexusConfig()
    _resolve_config_paths(config)
    return config


def load_config(path: Optional[str] = None) -> NexusConfig:
    """Load configuration from a JSON file.

    Reads the JSON file and overlays its values on top of the defaults.
    Any field not present in the file retains its default value.
    If the file does not exist or cannot be parsed, returns default config
    and prints a warning to stderr.

    Args:
        path: Path to the JSON configuration file. If None, uses the
              default config path from NexusConfig.

    Returns:
        A NexusConfig instance with loaded (or default) values.
    """
    default = get_default_config()

    if path is None:
        path = default.config_file

    config_path = _expand_path(path)

    if not os.path.isfile(config_path):
        import sys
        print(
            f"[Nexus] Config file not found at '{config_path}'. Using defaults.",
            file=sys.stderr,
        )
        return default

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        import sys
        print(
            f"[Nexus] Failed to parse config file '{config_path}': {e}. Using defaults.",
            file=sys.stderr,
        )
        return default
    except OSError as e:
        import sys
        print(
            f"[Nexus] Failed to read config file '{config_path}': {e}. Using defaults.",
            file=sys.stderr,
        )
        return default

    # Overlay loaded values onto defaults
    valid_fields = set(NexusConfig.__dataclass_fields__.keys())
    for key, value in data.items():
        if key in valid_fields:
            setattr(default, key, value)
        else:
            import sys
            print(
                f"[Nexus] Unknown config field '{key}' in '{config_path}'. Ignoring.",
                file=sys.stderr,
            )

    _resolve_config_paths(default)
    return default


def save_config(config: NexusConfig, path: Optional[str] = None) -> None:
    """Save configuration to a JSON file.

    Serializes all config fields to a human-readable JSON file. Creates
    parent directories if they do not exist.

    Args:
        config: The NexusConfig instance to persist.
        path: Path to write the JSON file. If None, uses config.config_file.
    """
    if path is None:
        path = config.config_file

    config_path = _expand_path(path)

    # Ensure parent directory exists
    parent_dir = os.path.dirname(config_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Convert config to dict, handling non-serializable types gracefully
    data = asdict(config)

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except OSError as e:
        import sys
        print(
            f"[Nexus] Failed to save config to '{config_path}': {e}",
            file=sys.stderr,
        )
