"""
Nexus — Core orchestrator.
Manages the REPL loop, LLM interaction, tool calling, and session lifecycle.

This module is the heart of Nexus. It ties together:
- The LLM backend for generating responses
- The tool registry for executing actions
- The safety validator for preventing destructive operations
- The display system for rich terminal output
- The conversation history for multi-turn context
- The workspace detector for project awareness
- The intent parser for quick-action shortcuts

The main entry point is the `main()` function, which parses CLI arguments
and launches the interactive REPL loop via `Nexus.run()`.

Developed under brutaltools.
"""

import os
import sys
import json
import signal
import time
from pathlib import Path
from typing import Optional, Dict, List, Any

from nexus.config import NexusConfig, load_config, save_config, get_default_config


class Nexus:
    """Core orchestrator for the Nexus AI assistant.

    Manages the full lifecycle of an interactive session, including:
    - Lazy-loading of all subsystems (LLM, tools, display, etc.)
    - The REPL (Read-Eval-Print Loop) for user interaction
    - Tool-calling loops with safety validation
    - Conversation history management
    - Context tracking for follow-up queries

    Usage:
        config = get_default_config()
        mind = Nexus(config)
        mind.run()

    Attributes:
        config: The active configuration instance.
    """

    def __init__(self, config: Optional[NexusConfig] = None):
        """Initialize Nexus with optional configuration.

        All subsystems are lazily loaded on first access to keep
        startup time minimal.

        Args:
            config: Optional configuration. Uses defaults if not provided.
        """
        self.config = config or get_default_config()
        self._llm = None  # lazy loaded LLM backend
        self._tool_registry = None  # lazy loaded tool registry
        self._chat_history = None  # lazy loaded conversation history
        self._workspace = None  # lazy loaded workspace detector
        self._safety_validator = None  # lazy loaded safety validator
        self._display = None  # lazy loaded display engine
        self._intent_parser = None  # lazy loaded intent parser
        self._running = False
        self._last_command = None
        self._last_file = None
        self._session_start_time = None
        self._total_tool_calls = 0
        self._total_messages = 0

    # ── Lazy-Loaded Properties ────────────────────────────────────────────

    @property
    def llm(self):
        """Lazy-load LLM backend.

        Returns the appropriate backend based on config.llm_backend.
        Supported backends: ollama, openai_compatible, mock.
        """
        if self._llm is None:
            from nexus.llm import get_backend
            self._llm = get_backend(self.config)
        return self._llm

    @property
    def tools(self):
        """Lazy-load tool registry with default tools registered.

        Also initializes the safety validator which is required for
        tool execution validation.
        """
        if self._tool_registry is None:
            from nexus.tools.registry import ToolRegistry
            from nexus.safety.validator import SafetyValidator
            self._safety_validator = SafetyValidator(config=self.config)
            self._tool_registry = ToolRegistry()
            self._tool_registry.register_defaults()
        return self._tool_registry

    @property
    def display(self):
        """Lazy-load the display engine for terminal output."""
        if self._display is None:
            from nexus.utils.display import Display
            self._display = Display(self.config)
        return self._display

    @property
    def workspace(self):
        """Lazy-load the workspace detector."""
        if self._workspace is None:
            from nexus.utils.workspace import Workspace
            self._workspace = Workspace(self.config.working_directory)
        return self._workspace

    @property
    def history(self):
        """Lazy-load the conversation history manager."""
        if self._chat_history is None:
            from nexus.chat.history import ChatHistory
            self._chat_history = ChatHistory(
                max_turns=self.config.max_history_turns,
                context_window=self.config.context_window,
                history_file=self.config.history_file
            )
        return self._chat_history

    @property
    def intent_parser(self):
        """Lazy-load the intent parser for quick actions."""
        if self._intent_parser is None:
            from nexus.utils.parser import IntentParser
            self._intent_parser = IntentParser()
        return self._intent_parser

    # ── Session Lifecycle ─────────────────────────────────────────────────

    def startup(self):
        """Initialize workspace awareness and show welcome banner.

        Detects the current project workspace, checks LLM backend
        availability, and displays the welcome message.
        """
        # Detect workspace
        self.workspace.detect()

        # Show welcome banner
        self.display.welcome(self.workspace.info, self.config)

        # Check LLM backend availability
        self._check_backend_status()

        # Record session start time
        self._session_start_time = time.time()

    def _check_backend_status(self):
        """Check if the configured LLM backend is reachable and show warnings."""
        try:
            health = self.llm.health_check()
            if health.get("status") == "ok":
                model = health.get("model", "unknown")
                backend = health.get("backend", "unknown")
                self.display.info(f"Connected to {backend} backend, model: {model}")
            elif health.get("status") == "no_models":
                self.display.warning(
                    f"{health.get('backend', 'LLM')} backend is running but no models found. "
                    "Pull a model or set a different model name."
                )
            elif health.get("status") == "error":
                self.display.warning(
                    f"Cannot connect to LLM backend: {health.get('error', 'unknown error')}. "
                    "Make sure your chosen backend is running. "
                    "You can still use built-in tools and quick actions."
                )
        except Exception as e:
            self.display.warning(f"Backend health check failed: {e}")

    def run(self):
        """Main REPL loop. This is the primary entry point.

        Continuously reads user input, processes it through the LLM
        with tool calling, and displays responses until the user
        exits. Handles keyboard interrupts gracefully.
        """
        self._running = True
        self.startup()

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while self._running:
            try:
                user_input = self.display.prompt()

                # Skip empty input
                if not user_input or not user_input.strip():
                    continue

                user_input = user_input.strip()

                # Handle special commands
                if self._handle_special_command(user_input):
                    continue

                # Try quick action first (intent parser for direct tool usage)
                if self._try_quick_action(user_input):
                    continue

                # Process through LLM with tool calling
                self._process_message(user_input)

            except KeyboardInterrupt:
                self.display.warning("\nInterrupted. Type 'exit' to quit or continue...")
            except EOFError:
                self._running = False
                self.display.goodbye()
            except Exception as e:
                self.display.error(f"Unexpected error: {e}")
                if self.config.llm_backend == "mock":
                    self.display.info("(Running in mock mode — this is expected for testing)")

        # Save session summary
        self._on_session_end()

    def _handle_special_command(self, user_input: str) -> bool:
        """Handle built-in special commands that bypass the LLM.

        Args:
            user_input: The raw user input string.

        Returns:
            True if the command was handled, False otherwise.
        """
        lower = user_input.lower()

        # Exit commands
        if lower in ("exit", "quit", "bye", "q"):
            self._running = False
            self.display.goodbye()
            return True

        # Clear conversation history
        if lower == "clear":
            self.history.clear()
            self.display.info("Session context cleared.")
            return True

        # Show session stats
        if lower in ("stats", "info", "status"):
            self._show_stats()
            return True

        # Save config
        if lower == "save config":
            save_config(self.config)
            self.display.info(f"Configuration saved to {self.config.config_file}")
            return True

        # List available tools
        if lower in ("tools", "help tools"):
            self._list_tools()
            return True

        # Show help
        if lower in ("help", "?", "/help"):
            self._show_help()
            return True

        return False

    def _show_stats(self):
        """Display current session statistics."""
        ctx = self.get_context()
        elapsed = time.time() - self._session_start_time if self._session_start_time else 0

        self.display.info("─── Session Stats ───")
        self.display.info(f"  Session:       {ctx.get('session_name', 'unnamed')}")
        self.display.info(f"  Working dir:   {ctx.get('working_dir', 'unknown')}")
        self.display.info(f"  LLM Backend:   {ctx.get('llm_backend', 'unknown')}")
        self.display.info(f"  Model:         {ctx.get('model', 'unknown')}")
        self.display.info(f"  History turns: {ctx.get('history_length', 0)}")
        self.display.info(f"  Tool calls:    {self._total_tool_calls}")
        self.display.info(f"  Total msgs:    {self._total_messages}")
        self.display.info(f"  Elapsed:       {self._format_duration(elapsed)}")
        self.display.info(f"  Tools loaded:  {len(ctx.get('tools_available', []))}")

    def _list_tools(self):
        """List all available tools with their descriptions."""
        tool_names = self.tools.list_tools()  # Force lazy-load via property
        if not tool_names:
            self.display.info("No tools loaded.")
            return

        self.display.info("─── Available Tools ───")
        for name in tool_names:
            tool = self.tools.get_tool(name)
            description = tool.schema.description if tool and tool.schema else "No description"
            self.display.info(f"  {name:25s} {description}")

    def _show_help(self):
        """Display help information about built-in commands."""
        self.display.info("─── Nexus Help ───")
        self.display.info("  Built-in Commands:")
        self.display.info("    exit / quit / bye    Exit Nexus")
        self.display.info("    clear                Clear conversation history")
        self.display.info("    stats / info         Show session statistics")
        self.display.info("    tools                List available tools")
        self.display.info("    save config          Save current configuration")
        self.display.info("    help / ?             Show this help message")
        self.display.info("")
        self.display.info("  Quick Actions (bypass LLM):")
        self.display.info("    ls / dir             List files in current directory")
        self.display.info("    pwd                  Show current directory")
        self.display.info("    cat <file>           Show file contents")
        self.display.info("    read <file>          Read file contents")
        self.display.info("    echo <text>          Echo text")
        self.display.info("")
        self.display.info("  Natural Language:")
        self.display.info("    Just type naturally! Nexus will use the LLM")
        self.display.info("    with tool calling to assist you.")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration in seconds to a human-readable string.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted string like '5m 32s' or '1h 5m 32s'.
        """
        if seconds < 60:
            return f"{seconds:.0f}s"
        minutes = int(seconds // 60)
        remainder = int(seconds % 60)
        if minutes < 60:
            return f"{minutes}m {remainder}s"
        hours = int(minutes // 60)
        minutes = int(minutes % 60)
        return f"{hours}h {minutes}m {remainder}s"

    # ── Signal Handling ───────────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        """Handle SIGINT and SIGTERM gracefully.

        Instead of crashing, shows a helpful message to the user.
        The REPL loop will continue running.

        Args:
            signum: The signal number received.
            frame: The current stack frame (unused).
        """
        self.display.warning("\nUse 'exit' to quit safely.")

    # ── Quick Actions ─────────────────────────────────────────────────────

    def _try_quick_action(self, user_input: str) -> bool:
        """Try intent parser for quick actions that bypass the LLM.

        Quick actions are simple, direct tool invocations that don't
        require LLM reasoning. Examples: 'ls', 'pwd', 'cat file.txt'.

        Args:
            user_input: The raw user input string.

        Returns:
            True if a quick action was handled, False to fall through
            to full LLM processing.
        """
        action = self.intent_parser.parse(user_input)
        if action is None:
            return False

        handler = self.tools.get_handler(action.tool_name)
        if handler is None:
            return False

        try:
            result = handler(**action.params)
            if hasattr(result, 'to_dict'):
                result_dict = result.to_dict()
            elif isinstance(result, dict):
                result_dict = result
            else:
                result_dict = {"success": True, "output": str(result)}
            self.display.show_result(result_dict)
            self.history.add("assistant", result_dict.get("display", result_dict.get("output", str(result_dict))))
            return True
        except Exception as e:
            self.display.error(f"Quick action failed: {e}")
            return False

    # ── LLM Message Processing ────────────────────────────────────────────

    def _process_message(self, user_input: str):
        """Process a message through the LLM with tool-calling loop.

        This implements the core agent loop:
        1. Add user message to history
        2. Build message list for LLM
        3. Send to LLM (with tool schemas if enabled)
        4. If LLM responds with tool calls, execute them and loop back
        5. If LLM responds with text, display it and end the turn

        Args:
            user_input: The user's input message.
        """
        self.history.add("user", user_input)
        self._total_messages += 1

        # Build the full message list including system prompt and history
        messages = self._build_messages()

        max_iterations = self.config.max_tool_calls_per_turn
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Get LLM response
            try:
                response = self.llm.chat(
                    messages=messages,
                    tools=self.tools.get_schemas() if self.config.tool_calling_enabled else None,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    stream=self.config.streaming,
                )
            except ConnectionError as e:
                self.display.error(f"Cannot reach LLM backend: {e}")
                self.display.info("Ensure your LLM backend server is running.")
                return
            except Exception as e:
                self.display.error(f"LLM error: {e}")
                return

            # Handle tool calls in response
            if response.tool_calls and self.config.tool_calling_enabled:
                # Append assistant message with tool calls to conversation
                messages.append(response.to_message())

                # Execute each tool call
                for tool_call in response.tool_calls:
                    tool_name = tool_call.name
                    tool_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                    tool_id = tool_call.id

                    # Display tool call to user
                    if self.config.show_tool_calls:
                        self.display.tool_call(tool_name, tool_args)

                    self._total_tool_calls += 1

                    # Validate safety before execution
                    tool_result = self._safe_execute_tool(tool_name, tool_args)

                    # Truncate large outputs to prevent context overflow
                    result_str = json.dumps(tool_result, default=str, ensure_ascii=False)
                    if len(result_str) > self.config.max_command_output_chars:
                        result_str = (
                            result_str[: self.config.max_command_output_chars]
                            + "\n... (truncated)"
                        )

                    # Append tool result to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result_str,
                    })

                # Loop back to send tool results to LLM for final synthesis
                continue

            # No tool calls — this is the final text response
            if response.content:
                self.display.assistant(response.content)
                self.history.add("assistant", response.content)

            # Update context tracking (last file, last command)
            self._update_context_tracking(response.content, messages)
            break

        else:
            # Exhausted max tool call iterations
            self.display.warning(
                f"Reached maximum tool call iterations ({max_iterations}). "
                "Returning current results."
            )

    def _safe_execute_tool(self, tool_name: str, tool_args: dict) -> dict:
        """Execute a tool with full safety validation.

        Checks the safety validator before execution. If the action is
        destructive and confirmation is enabled, prompts the user.

        Args:
            tool_name: Name of the tool to execute.
            tool_args: Arguments to pass to the tool.

        Returns:
            Dict with tool execution results or error information.
        """
        # Validate safety before execution
        is_safe, warning = self._safety_validator.validate_tool_call(tool_name, tool_args)

        if not is_safe:
            self.display.warning(f"Blocked: {warning}")
            return {"error": f"Safety blocked: {warning}"}

        # Check for destructive actions that need confirmation
        if (
            self.config.confirm_destructive
            and self._safety_validator.is_destructive(tool_name, tool_args)
        ):
            confirmed = self.display.confirm(
                f"Destructive action detected: {tool_name}({json.dumps(tool_args, indent=2)})\n"
                "Proceed?"
            )
            if not confirmed:
                return {"error": "User cancelled destructive action."}

        return self._execute_tool(tool_name, tool_args)

    def _execute_tool(self, name: str, args: dict) -> dict:
        """Execute a tool by name with given arguments.

        Args:
            name: The registered tool name.
            args: Keyword arguments for the tool handler.

        Returns:
            Dict with tool execution results or error information.
        """
        handler = self.tools.get_handler(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler(**args)
        except FileNotFoundError as e:
            return {"error": f"File not found: {e}"}
        except PermissionError as e:
            return {"error": f"Permission denied: {e}"}
        except TimeoutError:
            return {"error": f"Tool '{name}' timed out after {self.config.command_timeout}s"}
        except Exception as e:
            return {"error": f"Tool execution error ({name}): {e}"}

    # ── Message Building ──────────────────────────────────────────────────

    def _build_messages(self) -> list:
        """Build the full message list for the LLM.

        Constructs the complete conversation including:
        1. System prompt with workspace context and tool descriptions
        2. Conversation history (user/assistant/tool messages)

        Returns:
            List of message dicts ready for the LLM API.
        """
        from nexus.chat.templates import get_system_prompt

        system_prompt = get_system_prompt(self.workspace.info, self.config)
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        for msg in self.history.get_messages():
            messages.append(msg)

        return messages

    # ── Context Tracking ──────────────────────────────────────────────────

    def _update_context_tracking(self, content: str, messages: list):
        """Track last referenced files and commands for context awareness.

        Parses LLM responses for file path and command references,
        storing them for potential follow-up queries.

        Args:
            content: The LLM's response text.
            messages: The full message list (unused, reserved for future use).
        """
        import re

        # Track file references (patterns like file.py, /path/to/file, ~/file.txt)
        file_pattern = r"`?([~/\w.\-]+\.\w+)`?"
        files = re.findall(file_pattern, content)
        if files:
            self._last_file = files[-1]

        # Track command references (patterns like "ran: `ls -la`")
        cmd_pattern = r"(?:ran|executed|command):\s*`([^`]+)`"
        cmds = re.findall(cmd_pattern, content, re.IGNORECASE)
        if cmds:
            self._last_command = cmds[-1]

    # ── Session End ───────────────────────────────────────────────────────

    def _on_session_end(self):
        """Clean up and save session state when the REPL loop exits."""
        try:
            # Persist conversation history
            if self._chat_history is not None:
                self.history.save()
        except Exception as e:
            self.display.warning(f"Failed to save history: {e}")

    # ── Public API ────────────────────────────────────────────────────────

    def get_context(self) -> dict:
        """Get current session context for display or inspection.

        Returns a dictionary with information about the current session
        state, including working directory, available tools, and more.

        Returns:
            Dict with session context information.
        """
        return {
            "session_name": self.config.session_name,
            "working_dir": self.workspace.info.get("cwd", os.getcwd()),
            "history_length": len(self.history) if self._chat_history else 0,
            "tools_available": self.tools.list_tools(),  # Force lazy-load
            "llm_backend": self.config.llm_backend,
            "model": (
                self.config.ollama_model
                if self.config.llm_backend == "ollama"
                else self.config.openai_model
            ),
            "last_file": self._last_file,
            "last_command": self._last_command,
            "total_tool_calls": self._total_tool_calls,
            "total_messages": self._total_messages,
        }

    def ask(self, question: str) -> str:
        """Non-interactive: ask a single question and get a response.

        This method provides a programmatic API for scripting. It processes
        one question through the full LLM + tool-calling loop and returns
        the final text response.

        Args:
            question: The user's question or instruction.

        Returns:
            The LLM's final text response.
        """
        self._process_message(question)
        # Return the last assistant message from history
        messages = self.history.get_messages()
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                return msg["content"]
        return ""


def main():
    """Entry point for Nexus CLI.

    Parses command-line arguments, loads configuration, creates the
    Nexus instance, and starts the interactive REPL loop.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Nexus — Local Terminal AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nexus                          # Start with defaults (ollama + llama3)
  nexus --backend ollama --model codellama
  nexus --backend openai_compatible --model my-model
  nexus --no-tools               # Disable tool calling
  nexus --no-stream              # Disable streaming output
  nexus --session my-project     # Name the session
  nexus --config ~/.nexus/custom.json

Built-in Commands (in session):
  exit / quit / bye    Exit Nexus
  clear                Clear conversation history
  stats                Show session statistics
  tools                List available tools
  help                 Show help message
        """,
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config file (JSON)",
    )
    parser.add_argument(
        "--backend", "-b",
        type=str,
        choices=["ollama", "openai_compatible", "mock"],
        default=None,
        help="LLM backend to use (default: ollama)",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Model name to use",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        default=False,
        help="Disable tool calling entirely",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        default=False,
        help="Disable streaming output",
    )
    parser.add_argument(
        "--session", "-s",
        type=str,
        default=None,
        help="Name for this session",
    )
    parser.add_argument(
        "--workdir", "-w",
        type=str,
        default=None,
        help="Working directory for file/shell operations",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"Nexus v{__import__('nexus').__version__}",
    )

    args = parser.parse_args()

    # Load configuration (from file or defaults)
    config = load_config(args.config) if args.config else get_default_config()

    # Apply CLI overrides
    if args.backend:
        config.llm_backend = args.backend
    if args.model:
        if config.llm_backend == "ollama":
            config.ollama_model = args.model
        else:
            config.openai_model = args.model
    if args.no_tools:
        config.tool_calling_enabled = False
    if args.no_stream:
        config.streaming = False
    if args.session:
        config.session_name = args.session
    if args.workdir:
        config.working_directory = args.workdir

    # Create and run Nexus
    mind = Nexus(config)
    mind.run()
    return 0
