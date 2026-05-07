"""LLM backends for Nexus.

This package provides a unified interface for communicating with various
local LLM backends. Each backend implements the LLMBackend abstract interface
from nexus.llm.backend.

Supported backends:
- OllamaBackend: For the ollama local LLM runner
- OpenAICompatBackend: For any openai-compatible API server
- MockBackend: Returns predefined responses for testing and development

Developed under brutaltools.

Usage:
    from nexus.llm import get_backend
    backend = get_backend(config)
    response = backend.chat(messages=[...], tools=[...])
"""

from nexus.llm.backend import LLMBackend, LLMResponse, ToolCall
from nexus.llm.ollama import OllamaBackend
from nexus.llm.openai_compat import OpenAICompatBackend
from nexus.llm.mock import MockBackend


def get_backend(config):
    """Factory function to get the appropriate LLM backend.

    Reads config.llm_backend to determine which backend class to
    instantiate. Each backend receives the full config object for
    access to model names, URLs, and other parameters.

    Args:
        config: A NexusConfig instance with at least 'llm_backend' set.

    Returns:
        An instance of the appropriate LLMBackend subclass.

    Raises:
        ValueError: If config.llm_backend is not a recognized backend name.

    Examples:
        >>> backend = get_backend(config)  # config.llm_backend == "ollama"
        >>> isinstance(backend, OllamaBackend)
        True
        >>> response = backend.chat(messages=[{"role": "user", "content": "Hello"}])
    """
    backends = {
        "ollama": OllamaBackend,
        "openai_compatible": OpenAICompatBackend,
        "mock": MockBackend,
    }
    backend_cls = backends.get(config.llm_backend)
    if backend_cls is None:
        raise ValueError(
            f"Unknown LLM backend: {config.llm_backend}. "
            f"Choose from: {list(backends.keys())}"
        )
    return backend_cls(config)
