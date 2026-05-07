"""Terminal and command execution tools."""

import io
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Internal state for background processes
# =====================================================================

_background_processes: Dict[int, Dict[str, Any]] = {}
_bg_lock = threading.Lock()


# =====================================================================
# Tool implementations
# =====================================================================

def run_command(
    command: str,
    timeout: int = 30,
    working_dir: Optional[str] = None,
    capture_output: bool = True,
) -> Dict[str, Any]:
    """Execute a shell command and return stdout, stderr, and return code."""
    if not command or not command.strip():
        return {"error": "Empty command."}

    cwd = os.path.abspath(os.path.expanduser(working_dir)) if working_dir else None
    if cwd and not os.path.isdir(cwd):
        return {"error": f"Working directory does not exist: {cwd}"}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ},
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        output = ""
        if stdout:
            output += stdout
        if stderr:
            output += ("\n" if output else "") + stderr
        return {
            "output": output,
            "error": f"Command timed out after {timeout}s",
            "data": {
                "return_code": -1,
                "timed_out": True,
                "timeout": timeout,
                "stdout": stdout,
                "stderr": stderr,
            },
        }
    except Exception as exc:
        return {"error": f"Failed to execute command: {exc}"}

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    output = ""
    if stdout:
        output = stdout
    if stderr:
        output += ("\n" if output else "") + stderr

    # Truncate very large output
    max_len = 500_000
    truncated = False
    if len(output) > max_len:
        output = output[:max_len] + f"\n... (truncated, {len(output)} total chars)"
        truncated = True

    return {
        "output": output,
        "display": output,
        "data": {
            "return_code": result.returncode,
            "stdout": stdout if not truncated else stdout[:max_len],
            "stderr": stderr if not truncated else stderr[:max_len],
            "timed_out": False,
            "truncated": truncated,
        },
    }


def run_python(code: str) -> Dict[str, Any]:
    """Execute Python code and return its output or errors."""
    if not code or not code.strip():
        return {"error": "Empty code."}

    # Capture stdout/stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    sys.stdout = stdout_buf
    sys.stderr = stderr_buf

    # Controlled namespace
    ns: Dict[str, Any] = {
        "__builtins__": __builtins__,
        "os": os,
        "sys": sys,
        "json": __import__("json"),
        "math": __import__("math"),
        "re": __import__("re"),
        "datetime": __import__("datetime"),
        "collections": __import__("collections"),
        "itertools": __import__("itertools"),
        "pprint": __import__("pprint"),
        "subprocess": __import__("subprocess"),
        "pathlib": __import__("pathlib"),
        "shutil": __import__("shutil"),
    }

    result_value = None
    error_msg = ""

    try:
        # Use exec for statements, eval for expressions
        try:
            compiled = compile(code, "<nexus_code>", "eval")
            result_value = eval(compiled, ns)
        except SyntaxError:
            compiled = compile(code, "<nexus_code>", "exec")
            exec(compiled, ns)

        if result_value is not None:
            print(repr(result_value))
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"

    sys.stdout = old_stdout
    sys.stderr = old_stderr

    stdout_text = stdout_buf.getvalue()
    stderr_text = stderr_buf.getvalue()

    parts = []
    if stdout_text:
        parts.append(stdout_text.rstrip())
    if error_msg:
        parts.append(f"Error: {error_msg}")
    if stderr_text:
        parts.append(stderr_text.rstrip())

    output = "\n".join(parts) if parts else "(no output)"

    return {
        "output": output,
        "display": output,
        "data": {
            "result": repr(result_value) if result_value is not None else None,
            "error": error_msg if error_msg else None,
        },
    }


def pipe_commands(
    commands: List[str],
    timeout: int = 30,
) -> Dict[str, Any]:
    """Chain shell commands together with pipes."""
    if not commands:
        return {"error": "No commands provided."}

    for i, cmd in enumerate(commands):
        if not cmd or not cmd.strip():
            return {"error": f"Empty command at index {i}."}

    try:
        processes = []
        prev_stdout = None

        for i, cmd in enumerate(commands):
            is_last = (i == len(commands) - 1)
            stdin_arg = prev_stdout if prev_stdout else subprocess.PIPE
            stdout_arg = subprocess.PIPE if not is_last else subprocess.PIPE

            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=stdin_arg,
                stdout=stdout_arg,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(proc)

            if prev_stdout:
                prev_stdout.close()
            prev_stdout = proc.stdout

        # Communicate with the last process, with timeout via threads
        def _communicate():
            return processes[-1].communicate(timeout=timeout)

        try:
            last_stdout, last_stderr = _communicate()
        except subprocess.TimeoutExpired:
            for p in processes:
                p.kill()
            return {
                "output": "",
                "error": f"Piped command chain timed out after {timeout}s",
                "data": {"timed_out": True, "timeout": timeout},
            }

        # Close intermediate processes
        for p in processes[:-1]:
            p.wait()

        return_codes = [p.returncode for p in processes]

        output = last_stdout or ""
        if last_stderr:
            output += ("\n" if output else "") + last_stderr

        return {
            "output": output,
            "display": output,
            "data": {
                "return_codes": return_codes,
                "num_commands": len(commands),
                "pipeline": " | ".join(commands),
            },
        }
    except Exception as exc:
        return {"error": f"Failed to execute piped commands: {exc}"}


def background_process(command: str) -> Dict[str, Any]:
    """Start a background process and return its PID."""
    if not command or not command.strip():
        return {"error": "Empty command."}

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except Exception as exc:
        return {"error": f"Failed to start process: {exc}"}

    pid = proc.pid
    with _bg_lock:
        _background_processes[pid] = {
            "process": proc,
            "command": command,
            "started_at": time.time(),
        }

    return {
        "output": f"Background process started with PID {pid}: {command}",
        "data": {"pid": pid, "command": command},
    }


def kill_process(
    pid: Optional[int] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Kill a process by PID or by name."""
    if pid is None and name is None:
        return {"error": "Provide either 'pid' or 'name'."}

    if pid is not None:
        with _bg_lock:
            bg = _background_processes.get(pid)

        try:
            os.kill(pid, signal.SIGTERM)
            # Wait briefly
            time.sleep(0.1)
            try:
                os.kill(pid, 0)  # Check if still alive
                # Force kill
                os.kill(pid, signal.SIGKILL)
                method = "SIGKILL"
            except ProcessLookupError:
                method = "SIGTERM (already exited)"

            with _bg_lock:
                _background_processes.pop(pid, None)

            return {
                "output": f"Process {pid} terminated ({method})",
                "data": {"pid": pid, "method": method, "was_background": bg is not None},
            }
        except ProcessLookupError:
            return {"error": f"No process found with PID {pid}"}
        except PermissionError:
            return {"error": f"Permission denied to kill process {pid}"}
        except Exception as exc:
            return {"error": f"Failed to kill process {pid}: {exc}"}

    if name is not None:
        # Find PIDs by name using pgrep
        try:
            result = subprocess.run(
                ["pgrep", "-f", name],
                capture_output=True, text=True, timeout=5,
            )
            pids = [int(p) for p in result.stdout.strip().split("\n") if p.strip()]
        except Exception:
            pids = []

        if not pids:
            return {"error": f"No processes found matching '{name}'"}

        killed = []
        failed = []
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
                killed.append(p)
            except Exception:
                failed.append(p)

        with _bg_lock:
            for p in killed:
                _background_processes.pop(p, None)

        output = f"Killed {len(killed)} process(es) matching '{name}'"
        if failed:
            output += f". Failed to kill: {failed}"
        return {
            "output": output,
            "data": {"killed_pids": killed, "failed_pids": failed, "name": name},
        }

    return {"error": "Provide either 'pid' or 'name'."}


# =====================================================================
# Registration
# =====================================================================

_TERMINAL_TOOLS = [
    (
        "run_command",
        "Execute a shell command. Returns stdout, stderr, and exit code. "
        "Supports timeout and custom working directory.",
        [
            ToolParameter("command", "string", "The shell command to execute"),
            ToolParameter("timeout", "integer", "Timeout in seconds", required=False, default=30),
            ToolParameter("working_dir", "string", "Working directory", required=False, default=None),
            ToolParameter("capture_output", "boolean", "Capture stdout/stderr", required=False, default=True),
        ],
        run_command,
        True,
    ),
    (
        "run_python",
        "Execute Python code in a sandboxed namespace with access to common stdlib modules. "
        "Returns output or errors.",
        [
            ToolParameter("code", "string", "Python code to execute"),
        ],
        run_python,
        False,
    ),
    (
        "pipe_commands",
        "Chain multiple shell commands with pipes (|). Data flows from one command to the next.",
        [
            ToolParameter("commands", "array", "List of shell commands to pipe together"),
            ToolParameter("timeout", "integer", "Timeout in seconds", required=False, default=30),
        ],
        pipe_commands,
        True,
    ),
    (
        "background_process",
        "Start a command as a background process. Returns the PID for later management.",
        [
            ToolParameter("command", "string", "The shell command to run in background"),
        ],
        background_process,
        True,
    ),
    (
        "kill_process",
        "Kill a running process by PID or by process name.",
        [
            ToolParameter("pid", "integer", "Process ID to kill", required=False, default=None),
            ToolParameter("name", "string", "Process name to search for and kill", required=False, default=None),
        ],
        kill_process,
        True,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all terminal tools with the given registry."""
    for name, desc, params, func, dangerous in _TERMINAL_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
