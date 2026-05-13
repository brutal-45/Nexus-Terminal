"""
Nexus — An intelligent AI assistant running entirely on the user's local machine.
Operates through the terminal with zero internet dependency for core functionality.

Nexus provides:
- Natural language terminal interaction via local LLM backends
- Tool-calling for file operations, shell commands, code execution, and more
- Safety validation to prevent destructive operations
- Session persistence and conversation history
- Workspace awareness for project-aware assistance
- Fully offline-capable operation

Usage:
    python -m nexus
    nexus --backend ollama --model llama3
    nexus --config ~/.nexus/my_config.json

Developed under brutaltools.
"""

__version__ = "1.0.0"
__author__ = "BrutalTools"

from nexus.main import Nexus
