# Nexus — Local Terminal AI Assistant

<p align="center">
  <strong>An intelligent AI assistant that runs entirely on your local machine.</strong><br>
  Zero internet dependency. Full privacy. Terminal-native.
</p>

--- 

**Developed under [Brutaltools](https://github.com/brutal-45)** 

---

## Table of Contents

- [What is Nexus?](#what-is-nexus)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
  - [Quick Install](#quick-install)
  - [Install from Source](#install-from-source)
  - [Install with pip (Editable Mode)](#install-with-pip-editable-mode)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Starting Nexus](#starting-nexus)
  - [Built-in Commands](#built-in-commands)
  - [Quick Actions](#quick-actions)
  - [CLI Options](#cli-options)
- [LLM Backends](#llm-backends)
  - [Setting Up ollama](#setting-up-ollama)
  - [Using an openai-compatible Server](#using-an-openai-compatible-server)
  - [Mock Mode (No LLM Needed)](#mock-mode-no-llm-needed)
- [Available Tools](#available-tools)
- [Safety System](#safety-system)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)
- [Guidelines](#guidelines)

---

## What is Nexus?

Nexus is a local-first AI assistant that operates through your terminal. It connects to LLM backends running on your machine and provides powerful tool-calling capabilities — file operations, shell commands, code execution, git management, and more — all without sending your data to the cloud.

Your data never leaves your machine. Nexus works offline after initial model setup.

## Features

- **Local & Private** — All processing happens on your machine. No data sent to external servers.
- **Tool Calling** — 46 built-in tools for file ops, shell commands, code analysis, git, data processing, and system management.
- **Multiple LLM Backends** — Supports ollama, openai-compatible servers, and a built-in mock backend.
- **Safety First** — Dangerous commands are blocked or require confirmation. Configurable safety rules.
- **Workspace Aware** — Auto-detects your project type, packages, and environment.
- **Session Persistence** — Conversation history is saved and restored between sessions.
- **Quick Actions** — Bypass the LLM for simple tasks like `ls`, `pwd`, `cat`, `git status`.
- **Rich Terminal Display** — Syntax highlighting, Markdown rendering, themed output (monokai, dracula, etc.).
- **Zero Internet Dependency** — Core functionality works fully offline.

## Requirements

- **Python 3.10+** (3.10, 3.11, 3.12 supported)
- **An LLM backend** (optional — mock mode works without one):
  - [ollama](https://github.com/ollama/ollama) (recommended)
  - Any openai-compatible API server
- **Optional packages** (enhance the experience):
  - `rich` — Rich terminal display with syntax highlighting and Markdown
  - `pyyaml` — YAML parsing support for data tools
  - `orjson` — Faster JSON handling

## Installation

### Quick Install

```bash
# 1. Clone the repository
git clone https://github.com/brutaltools/nexus.git
cd nexus

# 2. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows

# 3. Install Nexus
pip install -e .

# 4. Run Nexus
python -m nexus
```

### Install from Source

```bash
# Download and extract the source
cd /path/to/nexus

# Install with all optional dependencies
pip install -e ".[full]"

# Or install with just the basics
pip install -e .
```

### Install with pip (Editable Mode)

If you want to hack on Nexus and see changes immediately:

```bash
git clone https://github.com/brutaltools/nexus.git
cd nexus
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"   # Includes pytest for testing
```

## Configuration

Nexus uses a JSON configuration file located at `~/.nexus/config.json`. On first run, sensible defaults are used — no configuration file is required.

### Default Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `llm_backend` | `"ollama"` | Backend to use: `ollama`, `openai_compatible`, or `mock` |
| `ollama_base_url` | `http://localhost:11434` | ollama API server URL |
| `ollama_model` | `"llama3"` | Default model name |
| `openai_base_url` | `http://localhost:8080/v1` | openai-compatible server URL |
| `openai_model` | `"local-model"` | Model name for openai-compatible backend |
| `temperature` | `0.7` | Sampling temperature (0.0–2.0) |
| `max_tokens` | `4096` | Max tokens per response |
| `confirm_destructive` | `true` | Ask before destructive commands |
| `theme` | `"monokai"` | Terminal color theme |

### Custom Configuration

Create `~/.nexus/config.json`:

```json
{
  "llm_backend": "ollama",
  "ollama_model": "llama3",
  "temperature": 0.5,
  "theme": "dracula",
  "confirm_destructive": true,
  "max_tool_calls_per_turn": 8
}
```

Or use the `--config` flag:

```bash
nexus --config /path/to/my-config.json
```

## Usage

### Starting Nexus

```bash
# Start with defaults (ollama backend, llama3 model)
python -m nexus

# Specify backend and model
python -m nexus --backend ollama --model llama3

# Use openai-compatible backend
python -m nexus --backend openai_compatible --model my-model

# Use mock backend (no LLM server needed)
python -m nexus --backend mock

# Name your session
python -m nexus --session my-project

# Set working directory
python -m nexus --workdir /path/to/project
```

### Built-in Commands

These commands work inside the Nexus REPL without going through the LLM:

| Command | Description |
|---------|-------------|
| `exit`, `quit`, `bye` | Exit Nexus |
| `clear` | Clear conversation history |
| `stats`, `info` | Show session statistics |
| `tools` | List all available tools |
| `save config` | Save current configuration to disk |
| `help`, `?` | Show help message |

### Quick Actions

Quick actions bypass the LLM for instant results:

| Action | Example |
|--------|---------|
| `ls`, `dir` | List files in current directory |
| `pwd` | Show current directory |
| `cat <file>`, `read <file>` | Read file contents |
| `$ <command>` | Execute a shell command |
| `git status` | Show git status |
| `git log` | Show git log |

### CLI Options

```
nexus [OPTIONS]

Options:
  -c, --config PATH       Path to config file (JSON)
  -b, --backend TEXT      LLM backend: ollama, openai_compatible, mock
  -m, --model TEXT        Model name to use
  --no-tools              Disable tool calling
  --no-stream             Disable streaming output
  -s, --session TEXT      Name for this session
  -w, --workdir TEXT      Working directory
  -v, --version           Show version
  -h, --help              Show help
```

## LLM Backends

### Setting Up ollama

ollama is the recommended backend for running LLMs locally.

```bash
# Install ollama (see https://github.com/ollama/ollama for details)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3

# Start the server (if not already running)
ollama serve

# Run Nexus
python -m nexus --backend ollama --model llama3
```

### Using an openai-compatible Server

Nexus works with any server that implements the openai Chat Completions API:

```bash
# Point Nexus to your server
python -m nexus \
  --backend openai_compatible \
  --model my-model-name

# Or configure in config.json
# Set "openai_base_url" and "openai_model" fields
```

### Mock Mode (No LLM Needed)

For testing, development, or just using the built-in tools without an LLM:

```bash
python -m nexus --backend mock
```

The mock backend provides predefined responses and still supports tool calling patterns for testing.

## Available Tools

Nexus ships with **46 built-in tools** across 6 categories:

### File Operations
| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line numbers |
| `write_file` | Write content to a file |
| `edit_file` | Find and replace text in a file |
| `list_directory` | List directory contents with metadata |
| `search_files` | Search files by name or content |
| `file_info` | Get detailed file/directory metadata |
| `move_file` | Move or rename files |
| `delete_file` | Delete files or empty directories |
| `compress_files` | Create zip/tar/gz archives |
| `compare_files` | Compare two files (unified diff) |

### Terminal & Shell
| Tool | Description |
|------|-------------|
| `run_command` | Execute shell commands |
| `pipe_commands` | Chain commands with pipes |
| `background_process` | Start background processes |
| `kill_process` | Kill a process by PID or name |
| `install_package` | Install Python packages via pip |

### System Information
| Tool | Description |
|------|-------------|
| `system_info` | OS, kernel, hostname, uptime |
| `cpu_info` | CPU model, cores, speed, load |
| `memory_info` | RAM and swap usage |
| `disk_usage` | Disk space and top-level breakdown |
| `list_processes` | Running processes with filtering |
| `network_info` | Network interfaces and ports |
| `port_check` | Check what is using a port |
| `check_service` | Check if a service is running |

### Code & Development
| Tool | Description |
|------|-------------|
| `run_python` | Execute Python code in a sandbox |
| `analyze_code` | Detect language, count lines/functions/classes |
| `explain_code` | Return code for explanation |
| `lint_code` | Basic linting (long lines, trailing whitespace, etc.) |
| `run_tests` | Run pytest or unittest |
| `count_lines` | Count lines of code by language |
| `find_definitions` | Find class/function definitions |

### Git Operations
| Tool | Description |
|------|-------------|
| `git_status` | Working tree status |
| `git_log` | Commit history |
| `git_diff` | Show changes |
| `git_add` | Stage files |
| `git_commit` | Create commits |
| `git_branch` | Branch operations |
| `git_stash` | Stash operations |
| `git_remote` | Remote operations |

### Data Processing
| Tool | Description |
|------|-------------|
| `parse_json` | Parse and pretty-print JSON |
| `parse_csv` | Parse CSV files |
| `parse_yaml` | Parse YAML files |
| `parse_xml` | Parse XML files |
| `json_query` | Query JSON with dot-notation paths |
| `filter_data` | Filter CSV/JSON data by column values |
| `analyze_data` | Basic statistical analysis |
| `convert_format` | Convert between JSON, CSV, TSV, XML |

## Safety System

Nexus includes a comprehensive safety system to prevent accidental damage:

- **Command blocking** — Dangerous patterns like `rm -rf`, `DROP TABLE`, `mkfs` are blocked by default
- **Confirmation prompts** — Destructive actions require explicit `y/N` confirmation
- **Path protection** — Warnings when modifying configuration files (`.bashrc`, `.ssh/`, `.env`, etc.)
- **Input sanitization** — Null bytes and excessively long inputs are stripped
- **Audit logging** — All tool calls are logged in an in-memory ring buffer
- **Allow/block lists** — Tools can be explicitly allowed or blocked by administrators

## Project Structure

```
nexus/
├── __init__.py          # Package entry, version, author
├── __main__.py          # python -m nexus entry point
├── main.py              # Core orchestrator, REPL loop
├── config.py            # Configuration management
├── setup.py             # Setuptools packaging
├── pyproject.toml       # Build configuration
├── requirements.txt     # Python dependencies
├── README.md            # This file
│
├── chat/                # Conversation management
│   ├── __init__.py
│   ├── history.py       # Conversation history persistence
│   ├── context.py       # Context tracking for follow-ups
│   └── templates.py     # System prompt templates
│
├── llm/                 # LLM backend integrations
│   ├── __init__.py      # Backend factory
│   ├── backend.py       # Abstract base class
│   ├── ollama.py        # ollama backend
│   ├── openai_compat.py # openai-compatible backend
│   └── mock.py          # Mock backend for testing
│
├── tools/               # Tool system
│   ├── __init__.py
│   ├── base.py          # Tool/ToolResult/ToolSchema base classes
│   ├── registry.py      # Tool registry and discovery
│   ├── file_ops.py      # File operation tools
│   ├── terminal.py      # Shell and terminal tools
│   ├── system.py        # System information tools
│   ├── code.py          # Code analysis and execution tools
│   ├── git.py           # Git operation tools
│   └── data.py          # Data parsing and analysis tools
│
├── safety/              # Safety and validation
│   ├── __init__.py
│   ├── validator.py     # Safety validator (gatekeeper)
│   └── rules.py         # Safety rules engine
│
└── utils/               # Utilities
    ├── __init__.py
    ├── display.py       # Terminal display and theming
    ├── parser.py        # Intent parser for quick actions
    └── workspace.py     # Project workspace detection
```

## Contributing

Contributions are welcome! This project is developed under **brutaltools**.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

Please ensure all tests pass before submitting:

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT License — see the [LICENSE](LICENSE) file for details.

---

## Guidelines

This project is developed and maintained under **[Brutaltools](https://github.com/brutal-45)**.

### Development Principles

- **Local-first**: All core functionality must work offline. Internet-dependent features are optional additions, never requirements.
- **Privacy by design**: User data must never leave the local machine unless explicitly configured otherwise.
- **Safety by default**: Destructive operations require confirmation. Safety rules cannot be silently bypassed.
- **Modular architecture**: Each subsystem (LLM backends, tools, safety, display) is independently replaceable.
- **Zero hard dependencies**: The core framework runs on Python stdlib alone. `rich`, `pyyaml`, and `orjson` enhance the experience but are not required.
- **Extensible tool system**: Adding new tools is as simple as writing a Python function and registering it with the `ToolRegistry`.
- **Backward compatibility**: Configuration files and APIs should remain compatible across minor version updates.

### Code Standards

- Python 3.10+ with type hints
- Google-style docstrings for all public APIs
- 80-column line length (soft limit)
- All tool calls must pass through the `SafetyValidator`
- No external AI service branding in user-facing strings — use generic identifiers (e.g., "ollama" as a backend name, not a company endorsement)

### Reporting Issues

When reporting bugs, please include:
- Python version (`python --version`)
- Nexus version (`python -m nexus --version`)
- Backend type and model name
- Steps to reproduce
- Expected vs. actual behavior

---

<p align="center">
  <strong>Nexus</strong> — Your local AI assistant.<br>
  <sub>Developed under brutaltools | MIT License</sub>
</p>
