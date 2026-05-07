"""openai-compatible LLM backend.

This module provides the openaiCompatBackend class, which connects to any
server that implements the openai chat completions API. Compatible servers
include various local LLM runners and inference engines.

The API follows the standard OpenAI Chat Completions format:
    POST {base_url}/chat/completions
    {
        "model": "...",
        "messages": [...],
        "tools": [...],
        "temperature": ...,
        "max_tokens": ...
    }

Developed under brutaltools.

Usage:
    backend = OpenAICompatBackend(config)
    response = backend.chat(messages=[{"role": "user", "content": "Hello"}])
    models = backend.list_models()
    health = backend.health_check()
"""

import json
import urllib.request
import urllib.error
from typing import Optional, List, Generator
from .backend import LLMBackend, LLMResponse, ToolCall


class OpenAICompatBackend(LLMBackend):
    """Backend for openai-compatible LLM servers.

    Supports any server implementing the openai chat completions API v1.
    Handles both standard chat responses and function/tool calling in
    openai chat completions format.

    Attributes:
        base_url: The base URL of the openai-compatible API.
        api_key: API key for authentication (often unused for local servers).
        model: The model name to use for completions.
    """

    def __init__(self, config):
        """Initialize the openai-compatible backend.

        Args:
            config: NexusConfig with openai_base_url, openai_model,
                    and openai_api_key set.
        """
        super().__init__(config)
        self.base_url = config.openai_base_url.rstrip("/")
        # Ensure the base URL ends with /v1 or /chat/completions pattern
        self.api_key = config.openai_api_key
        self.model = config.openai_model
        self._available_models: Optional[list] = None

    def _request(
        self,
        endpoint: str,
        data: dict = None,
        method: str = "POST",
        stream: bool = False,
    ) -> dict:
        """Make an HTTP request to the openai-compatible API.

        Handles JSON serialization, authentication headers, and error
        handling for common failure modes.

        Args:
            endpoint: The API endpoint path (e.g., "/chat/completions").
            data: Optional dict to send as JSON body.
            method: HTTP method (default "POST").
            stream: Whether this is a streaming request.

        Returns:
            Parsed JSON response dict.

        Raises:
            ConnectionError: If the server is unreachable or returns an error.
        """
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")

        # Add authorization header if API key is set and not the default placeholder
        if self.api_key and self.api_key != "not-needed":
            req.add_header("Authorization", f"Bearer {self.api_key}")

        try:
            timeout = max(self.config.command_timeout * 3, 60)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8") if e.fp else ""
            except Exception:
                pass
            raise ConnectionError(
                f"openai-compatible API error {e.code}: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to openai-compatible server at {self.base_url}. "
                "Is the server running?"
            ) from e
        except Exception as e:
            raise ConnectionError(f"API request failed: {e}") from e

    def chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> LLMResponse:
        """Send a chat completion request to the openai-compatible server.

        Constructs a standard openai chat completions API request with
        messages, optional tool schemas, and generation parameters.

        Args:
            messages: List of message dicts with 'role' and 'content'.
                      Supports 'user', 'assistant', 'system', and 'tool' roles.
            tools: Optional list of tool schemas for function calling
                   in openai chat completions format.
            temperature: Sampling temperature (0.0 - 2.0).
            max_tokens: Maximum tokens to generate.
            stream: Whether to use streaming (handled at display level).

        Returns:
            LLMResponse with content, tool_calls, and usage stats.
        """
        payload = {
            "model": self.model,
            "messages": self._sanitize_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        # Add tools if provided (openai function calling format)
        if tools:
            payload["tools"] = tools

        response_data = self._request("/chat/completions", payload)

        # Parse the response
        return self._parse_response(response_data)

    def streaming_chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, None]:
        """Generator for streaming responses from the openai-compatible server.

        Implements Server-Sent Events (SSE) parsing for streaming responses.
        Each chunk is a JSON object with a 'choices' array.

        Args:
            messages: List of message dicts.
            tools: Optional tool schemas.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate.

        Yields:
            Individual content string chunks as they arrive.
        """
        payload = {
            "model": self.model,
            "messages": self._sanitize_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key and self.api_key != "not-needed":
            req.add_header("Authorization", f"Bearer {self.api_key}")

        timeout = max(self.config.command_timeout * 4, 120)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buffer = ""
            for chunk_bytes in iter(lambda: resp.read(1), b""):
                chunk_str = chunk_bytes.decode("utf-8", errors="replace")

                if chunk_str == "\n" and buffer.strip():
                    line = buffer.strip()
                    # SSE format: "data: {json}"
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                                # Check finish reason
                                if choices[0].get("finish_reason") == "stop":
                                    return
                        except json.JSONDecodeError:
                            pass
                    buffer = ""
                else:
                    buffer += chunk_str

    def list_models(self) -> list:
        """List available models from the openai-compatible server.

        Returns:
            A list of dicts, each with 'name' and 'id' for the model.
        """
        data = self._request("/models", method="GET")
        models = []
        for m in data.get("data", []):
            models.append({
                "name": m.get("id", m.get("name", "unknown")),
                "id": m.get("id", ""),
                "owned_by": m.get("owned_by", "unknown"),
                "created": m.get("created", 0),
            })
        self._available_models = models
        return models

    def health_check(self) -> dict:
        """Check server health and model availability.

        Attempts to connect to the server, list models, and verify
        the configured model is available.

        Returns:
            Dict with 'status', 'backend', 'url', 'model', and other info.
        """
        try:
            models = self.list_models()
            model_ids = [m.get("name", m.get("id", "")) for m in models]
            current_available = (
                self.model in model_ids
                or any(self.model in mid for mid in model_ids)
            )
            return {
                "status": "ok" if models else "no_models",
                "backend": "openai_compatible",
                "url": self.base_url,
                "model": self.model,
                "model_available": current_available,
                "available_models": model_ids,
                "total_models": len(models),
            }
        except ConnectionError as e:
            return {
                "status": "error",
                "backend": "openai_compatible",
                "url": self.base_url,
                "model": self.model,
                "error": str(e),
            }
        except Exception as e:
            return {
                "status": "error",
                "backend": "openai_compatible",
                "url": self.base_url,
                "model": self.model,
                "error": f"Unexpected error: {e}",
            }

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _parse_response(self, response_data: dict) -> LLMResponse:
        """Parse an openai-format chat completion response.

        Extracts content, tool calls, usage stats, and finish reason
        from the standard OpenAI response format.

        Args:
            response_data: The parsed JSON response from the API.

        Returns:
            An LLMResponse with all parsed fields.
        """
        choices = response_data.get("choices", [])
        if not choices:
            return LLMResponse(
                content="",
                finish_reason="no_choices",
                raw=response_data,
            )

        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "stop")

        # Extract content
        content = message.get("content", "") or ""

        # Extract tool calls
        tool_calls = []
        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                # Parse arguments - may be a JSON string or already a dict
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw_arguments": args}

                tool_calls.append(ToolCall(
                    name=func.get("name", ""),
                    arguments=args,
                    id=tc.get("id", ""),
                ))

        # Extract usage stats
        usage_info = response_data.get("usage", {})
        usage = {
            "prompt_tokens": usage_info.get("prompt_tokens", 0),
            "completion_tokens": usage_info.get("completion_tokens", 0),
            "total_tokens": usage_info.get("total_tokens", 0),
        }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            raw=response_data,
        )

    @staticmethod
    def _sanitize_messages(messages: list) -> list:
        """Sanitize message list for openai-compatible API.

        Ensures all messages have the required fields and removes
        any fields that might cause API errors.

        Args:
            messages: List of message dicts.

        Returns:
            Sanitized list of message dicts.
        """
        sanitized = []
        for msg in messages:
            clean = {"role": msg["role"]}

            # Handle content - must be string or None
            content = msg.get("content")
            if content is not None:
                clean["content"] = str(content)
            else:
                clean["content"] = ""

            # Forward tool_calls for assistant messages
            if "tool_calls" in msg:
                clean["tool_calls"] = msg["tool_calls"]

            # Forward tool role attributes
            if msg["role"] == "tool":
                clean["tool_call_id"] = msg.get("tool_call_id", "")

            sanitized.append(clean)

        return sanitized
