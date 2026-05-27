"""Entry point for: python -m nexus

This module enables running Nexus directly as a Python module:
    python -m nexus
    python -m nexus --backend ollama --model llama3
    python -m nexus --help

All argument parsing and startup logic is delegated to nexus.main:main().

Developed under BrutalTools.
"""

import sys
from nexus.main import main

if __name__ == "__main__":
    sys.exit(main())
