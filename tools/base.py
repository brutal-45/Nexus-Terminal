"""Base classes for the tool system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolParameter:
    """Describes a parameter for a tool."""
    name: str
    type: str  # "string", "integer", "number", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ToolSchema:
    """JSON Schema for a tool (sent to LLM)."""
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI function-calling format."""
        properties = {}
        required = []
        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    output: str
    data: Any = None
    display: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        result = {"success": self.success, "output": self.output}
        if self.error:
            result["error"] = self.error
        if self.data is not None:
            result["data"] = self.data
        return result


class Tool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema for LLM function calling."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass


class FunctionTool(Tool):
    """A tool backed by a simple function."""

    def __init__(self, name: str, description: str,
                 parameters: List[ToolParameter],
                 func: Callable,
                 dangerous: bool = False):
        self._schema = ToolSchema(name=name, description=description, parameters=parameters)
        self._func = func
        self._dangerous = dangerous

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    @property
    def is_dangerous(self) -> bool:
        return self._dangerous

    def execute(self, **kwargs) -> ToolResult:
        try:
            result = self._func(**kwargs)
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict):
                return ToolResult(success=True, output=result.get("output", str(result)),
                                 data=result, display=result.get("display", ""))
            return ToolResult(success=True, output=str(result))
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
