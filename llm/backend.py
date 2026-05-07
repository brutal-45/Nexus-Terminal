"""Abstract base class for LLM backends.

This module defines the interface that all LLM backends must implement.
Each backend wraps a specific LLM service (ollama, openai-compatible servers,
or a mock for testing) behind a common API.

Developed under brutaltools.

The key types are:
- ToolCall: Represents a function/tool invocation requested by the LLM
- LLMResponse: Represents the full response from the LLM (text + tool calls)
- LLMBackend: Abstract base class that all backends extend

All backends must implement:
- chat(): Send messages and get a response (with optional tool calling)
- list_models(): List available models
- health_check(): Return connectivity and status information
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class ToolCall:
    """Represents a tool/function call from the LLM.

    When the LLM decides it needs to use a tool, it returns one or more
    ToolCall objects specifying which tool to invoke and with what arguments.

    Attributes:
        name: The name of the tool/function to call.
        arguments: A dict of named arguments to pass to the tool.
        id: A unique identifier for this tool call (used to correlate
            with the tool result message in openai chat completions format).
    """

    name: str
    arguments: dict = field(default_factory=dict)
    id: str = ""

    def __str__(self) -> str:
        """Human-readable representation of the tool call."""
        args_str = json.dumps(self.arguments, ensure_ascii=False)
        if len(args_str) > 100:
            args_str = args_str[:97] + "..."
        return f"ToolCall({self.name}, {args_str})"


@dataclass
class LLMResponse:
    """Represents a response from the LLM.

    An LLM response may contain:
- Text content (the assistant's message to the user)
- Tool calls (requests to invoke tools/functions)
- Usage metadata (token counts for billing/monitoring)

    Attributes:
        content: The text content of the response. May be empty if the
                 response consists entirely of tool calls.
        tool_calls: List of ToolCall objects. May be empty if the response
                    is a pure text response.
        finish_reason: The reason the generation stopped. Common values:
                       "stop" (natural end), "length" (max tokens), "tool_calls".
        usage: Dict with token usage stats: prompt_tokens, completion_tokens, total_tokens.
        raw: The raw response object from the underlying API (for debugging).
    """

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Any = None

    def to_message(self) -> dict:
        """Convert response to an assistant message for the conversation.

        Produces a message dict in openai-compatible format that can be
        appended to the conversation history. When tool_calls are present,
        content is set to None per openai convention.

        Returns:
            A message dict with 'role' and either 'content' or 'tool_calls'.
        """
        if self.tool_calls:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": (
                                json.dumps(tc.arguments)
                                if isinstance(tc.arguments, dict)
                                else str(tc.arguments)
                            ),
                        },
                    }
                    for tc in self.tool_calls
                ],
            }
        else:
            msg = {"role": "assistant", "content": self.content}
        return msg

    def has_tool_calls(self) -> bool:
        """Check whether this response contains tool calls.

        Returns:
            True if there are one or more tool calls, False otherwise.
        """
        return len(self.tool_calls) > 0

    def __str__(self) -> str:
        """Human-readable summary of the response."""
        parts = []
        if self.content:
            preview = self.content[:100]
            if len(self.content) > 100:
                preview += "..."
            parts.append(f"content={preview!r}")
        if self.tool_calls:
            names = [tc.name for tc in self.tool_calls]
            parts.append(f"tool_calls={names}")
        parts.append(f"finish={self.finish_reason!r}")
        return f"LLMResponse({', '.join(parts)})"


class LLMBackend(ABC):
    """Abstract base class for all LLM backends.

    Every LLM backend (ollama, openai_compatible, mock, etc.) must
    extend this class and implement the abstract methods. This ensures
    a consistent interface for the core orchestrator.

    Subclasses must implement:
    - chat(): The primary method for sending messages and receiving responses
    - list_models(): Listing available models on the backend
    - health_check(): Checking connectivity and returning status info

    Subclasses may override:
    - is_available(): Default implementation calls list_models()
    """

    def __init__(self, config):
        """Initialize the backend with configuration.

        Args:
            config: A NexusConfig instance with backend-specific settings.
        """
        self.config = config

    @abstractmethod
    def chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> LLMResponse:
        """Send a chat completion request to the LLM.

        This is the primary method for interacting with the LLM. It accepts
        a list of conversation messages and optional tool schemas, and returns
        a structured response that may contain text and/or tool calls.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      Roles are typically "system", "user", "assistant", and "tool".
            tools: Optional list of tool schemas for function calling.
                   Each schema follows openai function calling format.
            temperature: Sampling temperature (0.0 = deterministic, 2.0 = creative).
            max_tokens: Maximum number of tokens to generate in the response.
            stream: Whether to stream the response (display-level streaming is
                    handled separately; this controls API-level streaming).

        Returns:
            LLMResponse with content and/or tool_calls.

        Raises:
            ConnectionError: If the backend is unreachable.
            ValueError: If the request parameters are invalid.
            RuntimeError: If the backend returns an error response.
        """
        pass

    @abstractmethod
    def list_models(self) -> list:
        """List available models from the backend.

        Returns:
            A list of dicts, each containing at least 'name' and optionally
            'size', 'family', and other metadata.

        Raises:
            ConnectionError: If the backend is unreachable.
        """
        pass

    def is_available(self) -> bool:
        """Check if the backend is reachable and operational.

        Default implementation calls list_models() and returns True
        if no exception is raised. Subclasses may override for a
        lighter-weight check.

        Returns:
            True if the backend is available, False otherwise.
        """
        try:
            self.list_models()
            return True
        except Exception:
            return False

    @abstractmethod
    def health_check(self) -> dict:
        """Return detailed health status of the backend.

        Returns a dict with at least:
        - 'status': One of "ok", "no_models", "error"
        - 'backend': The backend name (e.g., "ollama", "openai_compatible")
        - 'model': The configured model name

        Additional fields may include 'url', 'model_available',
        'available_models', 'total_models', 'error', etc.

        Returns:
            A dict with health status information.
        """
        pass

    def __repr__(self) -> str:
        """String representation of the backend."""
        return f"<{self.__class__.__name__}(model={getattr(self, 'model', 'unknown')})>"
