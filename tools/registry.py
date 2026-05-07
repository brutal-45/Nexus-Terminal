"""Tool registry — manages all available tools for the LLM."""

import importlib
from typing import Any, Callable, Dict, List, Optional, Type

from nexus.tools.base import (
    FunctionTool,
    Tool,
    ToolParameter,
    ToolResult,
    ToolSchema,
)


class ToolRegistry:
    """Central registry for all tools available to the LLM.

    Usage::

        reg = ToolRegistry()
        reg.register_defaults()
        schemas = reg.get_schemas()
        result = reg.call("read_file", path="/etc/hosts")
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._dangerous_allowed: bool = False

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a :class:`Tool` instance."""
        self._tools[tool.schema.name] = tool

    def register_function(
        self,
        name: str,
        description: str,
        parameters: List[ToolParameter],
        func: Callable,
        dangerous: bool = False,
    ) -> FunctionTool:
        """Convenience: create a :class:`FunctionTool` from a plain callable and register it."""
        tool = FunctionTool(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
            dangerous=dangerous,
        )
        self.register(tool)
        return tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name (no-op if not found)."""
        self._tools.pop(name, None)

    def clear(self) -> None:
        """Remove every registered tool."""
        self._tools.clear()

    # ------------------------------------------------------------------
    # Dangerous-tool policy
    # ------------------------------------------------------------------

    @property
    def dangerous_allowed(self) -> bool:
        return self._dangerous_allowed

    @dangerous_allowed.setter
    def dangerous_allowed(self, value: bool) -> None:
        self._dangerous_allowed = value

    def allow_dangerous(self, value: bool = True) -> None:
        self._dangerous_allowed = value

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def list_tools(self) -> List[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def get_tool(self, name: str) -> Optional[Tool]:
        """Retrieve a :class:`Tool` by name, or *None*."""
        return self._tools.get(name)

    def get_handler(self, name: str) -> Optional[Callable]:
        """Return a plain callable ``(**kwargs) -> ToolResult`` for *name*, or *None*.

        This is a thin wrapper around :meth:`get_tool` so callers can treat the
        result as a simple function.
        """
        tool = self.get_tool(name)
        if tool is None:
            return None
        return tool.execute

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_schemas(self) -> List[dict]:
        """Return OpenAI-format schemas for *all* registered tools.

        Dangerous tools are included only when
        :attr:`dangerous_allowed` is *True*.
        """
        schemas = []
        for name in sorted(self._tools):
            tool = self._tools[name]
            if isinstance(tool, FunctionTool) and tool.is_dangerous:
                if not self._dangerous_allowed:
                    continue
            schemas.append(tool.schema.to_openai_schema())
        return schemas

    def get_all_schemas(self) -> List[dict]:
        """Return OpenAI-format schemas for *all* tools regardless of danger flag."""
        schemas = []
        for name in sorted(self._tools):
            schemas.append(self._tools[name].schema.to_openai_schema())
        return schemas

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by *name* with the given keyword arguments.

        Returns a :class:`ToolResult`.  If the tool is not found or is
        dangerous and dangerous-mode is off, an error result is returned.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' is not registered.",
            )

        if isinstance(tool, FunctionTool) and tool.is_dangerous:
            if not self._dangerous_allowed:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"Tool '{name}' is marked as dangerous. "
                        "Enable dangerous mode to use it."
                    ),
                )

        return tool.execute(**kwargs)

    # ------------------------------------------------------------------
    # Default tool registration
    # ------------------------------------------------------------------

    def register_defaults(self) -> None:
        """Register every built-in tool shipped with Nexus.

        This imports each sub-module and calls its ``register_all(reg)``
        function, if it exists.  Missing sub-modules are silently skipped.
        """
        submodules = [
            "nexus.tools.file_ops",
            "nexus.tools.terminal",
            "nexus.tools.system",
            "nexus.tools.code",
            "nexus.tools.git",
            "nexus.tools.data",
        ]
        for mod_path in submodules:
            try:
                mod = importlib.import_module(mod_path)
                if hasattr(mod, "register_all"):
                    mod.register_all(self)
            except Exception as exc:
                # Silently skip so that missing optional deps don't crash init.
                pass

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        names = ", ".join(sorted(self._tools))
        return f"ToolRegistry([{names}])"
