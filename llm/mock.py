"""Mock LLM backend for testing and development.

This module provides the MockBackend class, which simulates LLM responses
without requiring an actual LLM server. It is useful for:

- Unit testing the Nexus framework
- Development without a running LLM server
- Demonstrating tool calling behavior
- Integration testing with predictable responses

The mock backend recognizes special patterns in user messages to trigger
specific behaviors:
- Messages starting with "tools:" or containing "[call_tool:..." trigger tool calls
- Messages starting with "error:" trigger simulated errors
- Messages starting with "empty:" trigger empty responses
- All other messages get a friendly canned response

Usage:
    backend = MockBackend(config)
    response = backend.chat(messages=[{"role": "user", "content": "Hello"}])
    # response.content == "Hello! I'm Nexus's mock backend..."
"""

import json
import random
import time
from typing import Optional, List, Generator
from .backend import LLMBackend, LLMResponse, ToolCall


# Predefined responses for common queries
_DEFAULT_RESPONSES = [
    "Hello! I'm Nexus's mock backend running in testing mode. "
    "In production, this would be a real LLM response. "
    "Tool calling and other features still work normally!",

    "I received your message. Since I'm running in mock mode, "
    "I'm returning a predefined response. The full LLM integration "
    "would provide contextual, intelligent replies.",

    "This is a simulated response from the mock backend. "
    "All framework features (tool calling, safety validation, "
    "history management) are fully operational.",

    "Mock backend active. I can process your messages and execute "
    "tools, but my responses are predefined rather than generated "
    "by a language model. This is useful for testing and development.",

    "Hi there! I'm the Nexus mock backend. I handle the full "
    "message processing pipeline including tool calling, but return "
    "canned responses instead of LLM-generated ones.",
]


class MockBackend(LLMBackend):
    """Mock LLM backend for testing and development.

    Simulates LLM behavior with configurable, predictable responses.
    Supports tool call simulation by recognizing patterns in user messages.
    Tracks call counts and timing for testing assertions.

    Attributes:
        model: The model name (always "mock-model").
        call_count: Number of times chat() has been called.
        last_messages: The messages from the most recent chat() call.
        response_delay: Simulated response delay in seconds.
    """

    def __init__(self, config):
        """Initialize the mock backend.

        Args:
            config: NexusConfig instance (used for timeout settings).
        """
        super().__init__(config)
        self.model = "mock-model"
        self._call_count = 0
        self._last_messages: list = []
        self._last_tools: Optional[list] = None
        self._response_delay: float = 0.05  # Small delay to simulate processing
        self._available_models = [
            {"name": "mock-model", "size": 0, "family": "mock"},
            {"name": "mock-large", "size": 0, "family": "mock"},
            {"name": "mock-code", "size": 0, "family": "mock"},
        ]
        self._custom_responses: dict = {}
        self._error_mode: bool = False

    def chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> LLMResponse:
        """Simulate a chat completion response.

        Analyzes the last user message for special patterns that trigger
        specific behaviors (tool calls, errors, empty responses).
        Otherwise returns a random predefined response.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional tool schemas (stored for reference).
            temperature: Sampling temperature (ignored in mock).
            max_tokens: Max tokens to generate (ignored in mock).
            stream: Whether streaming was requested (ignored in mock).

        Returns:
            LLMResponse with simulated content and/or tool_calls.
        """
        # Simulate processing delay
        time.sleep(self._response_delay)

        # Track call metrics
        self._call_count += 1
        self._last_messages = messages
        self._last_tools = tools

        # Check for error simulation mode
        if self._error_mode:
            raise RuntimeError("Mock backend is in error simulation mode")

        # Get the last user message for pattern matching
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_user_msg = content
                break

        # Check custom responses first
        for pattern, response in self._custom_responses.items():
            if pattern in last_user_msg:
                return self._build_response(response, tools)

        # Pattern-based behaviors
        if last_user_msg.startswith("error:"):
            error_msg = last_user_msg[6:].strip()
            raise RuntimeError(f"Mock error: {error_msg}")

        if last_user_msg.startswith("empty:"):
            return LLMResponse(
                content="",
                finish_reason="stop",
                usage=self._mock_usage(len(str(messages))),
            )

        if last_user_msg.startswith("tools:"):
            return self._simulate_tool_call(last_user_msg[6:].strip(), tools)

        # Check for [call_tool:name{"arg": "val"}] pattern
        if "[call_tool:" in last_user_msg:
            return self._parse_embedded_tool_call(last_user_msg, tools)

        # Default: return a random predefined response
        response_text = random.choice(_DEFAULT_RESPONSES)
        return LLMResponse(
            content=response_text,
            finish_reason="stop",
            usage=self._mock_usage(len(str(messages)) + len(response_text)),
        )

    def streaming_chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, None]:
        """Simulate streaming by yielding response word-by-word.

        Args:
            messages: List of message dicts.
            tools: Optional tool schemas.
            temperature: Sampling temperature (ignored).
            max_tokens: Max tokens (ignored).

        Yields:
            Individual word chunks with spaces.
        """
        response = self.chat(messages, tools, temperature, max_tokens, stream=False)
        words = response.content.split(" ")
        for i, word in enumerate(words):
            if i > 0:
                yield " "
            yield word
            time.sleep(0.02)  # Simulate token arrival delay

    def list_models(self) -> list:
        """Return a predefined list of mock models.

        Returns:
            A list of dicts with mock model metadata.
        """
        return list(self._available_models)

    def health_check(self) -> dict:
        """Return mock health status indicating the backend is operational.

        Returns:
            Dict with 'status': 'ok', 'backend': 'mock', and other info.
        """
        return {
            "status": "ok",
            "backend": "mock",
            "url": "mock://localhost",
            "model": self.model,
            "model_available": True,
            "available_models": [m["name"] for m in self._available_models],
            "total_models": len(self._available_models),
            "call_count": self._call_count,
        }

    # ── Testing Utilities ─────────────────────────────────────────────────

    def set_custom_response(self, pattern: str, response: str):
        """Register a custom response for messages containing the given pattern.

        When a user message contains the pattern string, the mock backend
        will return the specified response instead of a default one.

        Args:
            pattern: A substring to search for in user messages.
            response: The response text to return when the pattern matches.
        """
        self._custom_responses[pattern] = response

    def set_error_mode(self, enabled: bool = True):
        """Enable or disable error simulation mode.

        When enabled, every chat() call raises a RuntimeError.

        Args:
            enabled: True to enable error mode, False to disable.
        """
        self._error_mode = enabled

    def set_response_delay(self, delay: float):
        """Set the simulated processing delay in seconds.

        Args:
            delay: Delay in seconds (0 for no delay).
        """
        self._response_delay = max(0.0, delay)

    def reset(self):
        """Reset all mock state (call counts, custom responses, etc.)."""
        self._call_count = 0
        self._last_messages = []
        self._last_tools = None
        self._custom_responses = {}
        self._error_mode = False
        self._response_delay = 0.05

    @property
    def call_count(self) -> int:
        """Number of times chat() has been called."""
        return self._call_count

    @property
    def last_messages(self) -> list:
        """Messages from the most recent chat() call."""
        return list(self._last_messages)

    @property
    def last_tools(self) -> Optional[list]:
        """Tools from the most recent chat() call."""
        return self._last_tools

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _simulate_tool_call(
        self, tool_spec: str, available_tools: Optional[list]
    ) -> LLMResponse:
        """Simulate a tool call based on a specification string.

        The spec can be either:
        - A tool name: "read_file"
        - A tool name with JSON args: "read_file {\"path\": \"/tmp/test.txt\"}"

        Args:
            tool_spec: The tool call specification.
            available_tools: List of available tool schemas.

        Returns:
            LLMResponse with the simulated tool call.
        """
        # Parse tool name and optional arguments
        tool_spec = tool_spec.strip()
        if " " in tool_spec:
            tool_name = tool_spec.split(" ", 1)[0].strip()
            args_str = tool_spec.split(" ", 1)[1].strip()
            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError:
                arguments = {"raw_input": args_str}
        else:
            tool_name = tool_spec
            arguments = {}

        # Generate a unique ID for the tool call
        tool_id = f"mock_call_{self._call_count}_{int(time.time() * 1000)}"

        tool_call = ToolCall(
            name=tool_name,
            arguments=arguments,
            id=tool_id,
        )

        return LLMResponse(
            content="",
            tool_calls=[tool_call],
            finish_reason="tool_calls",
            usage=self._mock_usage(len(tool_spec)),
        )

    def _parse_embedded_tool_call(
        self, message: str, available_tools: Optional[list]
    ) -> LLMResponse:
        """Parse tool calls embedded in message using [call_tool:...] syntax.

        Supports multiple tool calls in a single message.

        Args:
            message: The user message containing embedded tool call patterns.
            available_tools: List of available tool schemas.

        Returns:
            LLMResponse with parsed tool calls.
        """
        tool_calls = []
        import re

        # Pattern: [call_tool:name{"arg": "val"}] or [call_tool:name]
        pattern = r"\[call_tool:(\w+)(\{[^}]*\})?\]"
        matches = re.findall(pattern, message)

        for i, (name, args_str) in enumerate(matches):
            arguments = {}
            if args_str:
                try:
                    arguments = json.loads(args_str)
                except json.JSONDecodeError:
                    arguments = {"raw_input": args_str}

            tool_calls.append(ToolCall(
                name=name,
                arguments=arguments,
                id=f"mock_embedded_{self._call_count}_{i}",
            ))

        if not tool_calls:
            return LLMResponse(
                content="I couldn't parse any tool calls from your message.",
                finish_reason="stop",
                usage=self._mock_usage(len(message)),
            )

        return LLMResponse(
            content="",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
            usage=self._mock_usage(len(message)),
        )

    @staticmethod
    def _build_response(content: str, tools: Optional[list]) -> LLMResponse:
        """Build an LLMResponse from a content string.

        Args:
            content: The response text.
            tools: Available tools (unused, reserved for future use).

        Returns:
            LLMResponse with the given content.
        """
        return LLMResponse(
            content=content,
            finish_reason="stop",
            usage=MockBackend._mock_usage(len(content)),
        )

    @staticmethod
    def _mock_usage(char_count: int) -> dict:
        """Generate mock token usage statistics.

        Roughly estimates token count as chars / 4 (average for English text).

        Args:
            char_count: Number of characters in the content.

        Returns:
            Dict with prompt_tokens, completion_tokens, and total_tokens.
        """
        estimated_tokens = max(1, char_count // 4)
        return {
            "prompt_tokens": estimated_tokens * 2,
            "completion_tokens": estimated_tokens,
            "total_tokens": estimated_tokens * 3,
        }
