"""ollama LLM backend — communicates with a local ollama server.

This module provides the ollamaBackend class, which connects to a locally
running ollama instance for LLM inference.

ollama is the recommended backend for Nexus as it:
- Runs entirely locally with no internet required after model download
- Supports native function/tool calling
- Provides streaming responses
- Has a simple REST API
- Supports a wide range of open-source models

Developed under brutaltools.

Usage:
    backend = OllamaBackend(config)
    response = backend.chat(messages=[{"role": "user", "content": "Hello"}])
    models = backend.list_models()
    health = backend.health_check()
"""

import json
import urllib.request
import urllib.error
from typing import Optional, List, Generator
from .backend import LLMBackend, LLMResponse, ToolCall


class OllamaBackend(LLMBackend):
    """Backend for ollama — runs LLMs locally.

    Connects to the ollama REST API running on localhost (default port 11434).
    Supports chat completions with optional tool calling, model management,
    and health monitoring.

    Attributes:
        base_url: The base URL of the ollama API server.
        model: The name of the model to use for completions.
    """

    def __init__(self, config):
        """Initialize the ollama backend.

        Args:
            config: NexusConfig with at least ollama_base_url and
                    ollama_model set.
        """
        super().__init__(config)
        self.base_url = config.ollama_base_url.rstrip("/")
        self.model = config.ollama_model
        self._available_models: Optional[list] = None

    def _request(self, endpoint: str, data: dict = None, method: str = "POST") -> dict:
        """Make an HTTP request to the ollama API.

        Handles JSON serialization, content-type headers, and error handling
        for common failure modes (connection refused, HTTP errors).

        Args:
            endpoint: The API endpoint path (e.g., "/api/chat").
            data: Optional dict to send as JSON body.
            method: HTTP method (default "POST").

        Returns:
            Parsed JSON response dict.

        Raises:
            ConnectionError: If the server is unreachable or returns an error.
        """
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")

        try:
            timeout = max(self.config.command_timeout * 2, 30)
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
                f"ollama API error {e.code}: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to ollama at {self.base_url}. "
                "Is ollama running? Start it with: ollama serve"
            ) from e
        except Exception as e:
            raise ConnectionError(f"ollama request failed: {e}") from e

    def chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> LLMResponse:
        """Send a chat completion request to ollama.

        Converts the standard message format to ollama's expected format,
        sends the request, and parses the response into an LLMResponse.
        Supports ollama's native tool calling when tools are provided.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool schemas for function calling.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            stream: Whether to use streaming (handled at display level).

        Returns:
            LLMResponse with content, tool_calls, and usage stats.
        """
        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # Add tools if provided (ollama native tool calling)
        if tools:
            payload["tools"] = self._convert_tools(tools)

        response_data = self._request("/api/chat", payload)

        # Parse tool calls from ollama response
        tool_calls = self._parse_tool_calls(response_data.get("message", {}))

        content = response_data.get("message", {}).get("content", "")

        # Calculate usage stats
        prompt_tokens = response_data.get("prompt_eval_count", 0)
        completion_tokens = response_data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=response_data.get("done_reason", "stop"),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            raw=response_data,
        )

    def streaming_chat(
        self,
        messages: list,
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, None]:
        """Generator for streaming responses from ollama.

        Yields content tokens as they arrive from the ollama API.
        Uses newline-delimited JSON (NDJSON) streaming format.

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
            "messages": self._convert_messages(messages),
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)

        url = f"{self.base_url}/api/chat"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")

        timeout = max(self.config.command_timeout * 4, 120)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buffer = ""
            for chunk_bytes in iter(lambda: resp.read(1), b""):
                chunk_str = chunk_bytes.decode("utf-8", errors="replace")

                if chunk_str == "\n" and buffer.strip():
                    try:
                        data = json.loads(buffer)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done", False):
                            return
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        pass
                    buffer = ""
                else:
                    buffer += chunk_str

            # Handle any remaining buffer content
            if buffer.strip():
                try:
                    data = json.loads(buffer)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    pass

    def list_models(self) -> list:
        """List available models from ollama.

        Returns:
            A list of dicts, each with 'name', 'size', 'modified', and 'family'.
        """
        data = self._request("/api/tags")
        models = []
        for m in data.get("models", []):
            models.append({
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "modified": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", "unknown"),
                "quantization": m.get("details", {}).get("quantization_level", "unknown"),
            })
        self._available_models = models
        return models

    def pull_model(self, model_name: str) -> str:
        """Pull/download a model from the ollama registry.

        Downloads the specified model if not already present locally.
        This may take a while for large models.

        Args:
            model_name: The name of the model to pull (e.g., "llama3", "codellama").

        Returns:
            A success message string.

        Raises:
            ConnectionError: If the download fails.
        """
        data = self._request(
            "/api/pull",
            {"name": model_name, "stream": False},
        )
        status = data.get("status", "unknown")
        return f"Model '{model_name}' pulled successfully. Status: {status}"

    def show_model_info(self, model_name: str = None) -> dict:
        """Show detailed information about a model.

        Returns metadata, template, system prompt, and modification
        details for the specified model.

        Args:
            model_name: The model to inspect. Defaults to the configured model.

        Returns:
            Dict with model details (license, template, system, etc.).
        """
        name = model_name or self.model
        return self._request("/api/show", {"name": name})

    def delete_model(self, model_name: str) -> str:
        """Delete a locally stored model.

        Args:
            model_name: The name of the model to delete.

        Returns:
            A success message string.
        """
        self._request("/api/delete", {"name": model_name}, method="DELETE")
        return f"Model '{model_name}' deleted successfully."

    def health_check(self) -> dict:
        """Check ollama server health and model availability.

        Attempts to connect to the ollama server, list models,
        and verify the configured model is available.

        Returns:
            Dict with 'status', 'backend', 'url', 'model', and other info.
        """
        try:
            models = self.list_models()
            model_names = [m["name"] for m in models]
            current_available = self.model in model_names or any(
                self.model in n for n in model_names
            )
            return {
                "status": "ok" if models else "no_models",
                "backend": "ollama",
                "url": self.base_url,
                "model": self.model,
                "model_available": current_available,
                "available_models": model_names,
                "total_models": len(models),
            }
        except ConnectionError as e:
            return {
                "status": "error",
                "backend": "ollama",
                "url": self.base_url,
                "model": self.model,
                "error": str(e),
            }
        except Exception as e:
            return {
                "status": "error",
                "backend": "ollama",
                "url": self.base_url,
                "model": self.model,
                "error": f"Unexpected error: {e}",
            }

    # ── Internal Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _convert_messages(messages: list) -> list:
        """Convert standard message format to ollama format.

        ollama expects messages as dicts with 'role' and 'content'.
        Tool messages also need 'tool_call_id' mapped to ollama's format.

        Args:
            messages: List of standard message dicts.

        Returns:
            List of Ollama-format message dicts.
        """
        ollama_messages = []
        for msg in messages:
            converted = {"role": msg["role"], "content": msg.get("content", "")}
            # Forward tool_calls in assistant messages
            if "tool_calls" in msg and msg["tool_calls"]:
                converted["tool_calls"] = msg["tool_calls"]
            # Forward tool results
            if "tool_call_id" in msg:
                converted["tool_call_id"] = msg["tool_call_id"]
            ollama_messages.append(converted)
        return ollama_messages

    @staticmethod
    def _convert_tools(tools: list) -> list:
        """Convert tool schemas to ollama's native tool format.

        ollama uses the same format as OpenAI for tool definitions.

        Args:
            tools: List of tool schema dicts.

        Returns:
            List of Ollama-format tool dicts.
        """
        ollama_tools = []
        for tool in tools:
            if "function" in tool:
                # Already in OpenAI format — ollama accepts this directly
                ollama_tools.append(tool)
            elif "name" in tool:
                # Simple format — wrap in function schema
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    },
                })
        return ollama_tools

    @staticmethod
    def _parse_tool_calls(message: dict) -> List[ToolCall]:
        """Parse tool calls from an ollama message response.

        Handles both ollama's native tool_calls format and OpenAI format.

        Args:
            message: The message dict from the ollama API response.

        Returns:
            List of ToolCall objects. Empty list if no tool calls found.
        """
        tool_calls = []

        # ollama native format
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append(ToolCall(
                    name=func.get("name", ""),
                    arguments=func.get("arguments", {}),
                    id=tc.get("id", ""),
                ))

        return tool_calls
