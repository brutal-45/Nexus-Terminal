"""System management tools — disk, memory, CPU, processes, network."""

import os
import platform
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Helpers
# =====================================================================

def _run(cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a command, returning CompletedProcess. Never raises."""
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return subprocess.CompletedProcess(cmd, -1, "", "")


def _safe_float(text: str) -> Optional[float]:
    """Extract the first float from *text*, or return None."""
    m = re.search(r"[\d]+(?:\.[\d]+)?", text)
    return float(m.group()) if m else None


def _format_bytes(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


# =====================================================================
# Tool implementations
# =====================================================================

def disk_usage(path: str = "/") -> Dict[str, Any]:
    """Show disk usage for a path, including top-level directory breakdown."""
    import shutil

    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        return {"error": f"Not a directory: {path}"}

    try:
        usage = shutil.disk_usage(path)
    except Exception as exc:
        return {"error": f"Could not get disk usage: {exc}"}

    total = usage.total
    used = usage.used
    free = usage.free
    pct = (used / total * 100) if total else 0

    lines = [
        f"Device/Filesystem : {path}",
        f"Total             : {_format_bytes(total)}",
        f"Used              : {_format_bytes(used)} ({pct:.1f}%)",
        f"Free              : {_format_bytes(free)}",
        f"Available         : {_format_bytes(usage.free)}",
    ]

    # Top-level directory sizes via `du`
    du_result = _run(f"du -sh {path}/* 2>/dev/null | sort -rh | head -20", timeout=10)
    if du_result.returncode == 0 and du_result.stdout.strip():
        lines.append("")
        lines.append("Top-level breakdown:")
        for entry in du_result.stdout.strip().split("\n"):
            lines.append(f"  {entry.strip()}")

    output = "\n".join(lines)
    return {
        "output": output,
        "display": output,
        "data": {
            "path": path,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "percent_used": round(pct, 1),
        },
    }


def memory_info() -> Dict[str, Any]:
    """Show system memory usage."""
    system = platform.system()
    data: Dict[str, Any] = {}
    lines: List[str] = []

    if system == "Linux":
        meminfo_path = "/proc/meminfo"
        if os.path.isfile(meminfo_path):
            try:
                with open(meminfo_path, "r") as fh:
                    mi = {}
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        key, _, val = raw.partition(":")
                        # val is like "12345 kB"
                        num = _safe_float(val)
                        mi[key.strip()] = num
                    data["meminfo_kb"] = mi

                    total = mi.get("MemTotal", 0)
                    free = mi.get("MemFree", 0)
                    available = mi.get("MemAvailable", free)
                    buffers = mi.get("Buffers", 0)
                    cached = mi.get("Cached", 0)
                    used = total - available

                    lines = [
                        f"Total        : {_format_bytes(total * 1024)}",
                        f"Used         : {_format_bytes(used * 1024)} ({used / total * 100:.1f}%)" if total else "Used         : N/A",
                        f"Free         : {_format_bytes(free * 1024)}",
                        f"Available    : {_format_bytes(available * 1024)}",
                        f"Buffers      : {_format_bytes(buffers * 1024)}",
                        f"Cached       : {_format_bytes(cached * 1024)}",
                    ]

                    # Swap
                    swap_total = mi.get("SwapTotal", 0)
                    if swap_total and swap_total > 0:
                        swap_free = mi.get("SwapFree", 0)
                        swap_used = swap_total - swap_free
                        lines.append("")
                        lines.append("Swap:")
                        lines.append(f"  Total   : {_format_bytes(swap_total * 1024)}")
                        lines.append(f"  Used    : {_format_bytes(swap_used * 1024)}")
                        lines.append(f"  Free    : {_format_bytes(swap_free * 1024)}")

                    data["total_kb"] = total
                    data["used_kb"] = used
                    data["available_kb"] = available
            except Exception as exc:
                return {"error": f"Could not read /proc/meminfo: {exc}"}
        else:
            return {"error": "Memory info not available (no /proc/meminfo)"}
    else:
        # Fallback: try `vm_stat` on macOS, `systeminfo` on Windows
        if system == "Darwin":
            result = _run("vm_stat")
            if result.returncode == 0:
                lines.append(result.stdout)
            else:
                lines.append("Could not retrieve memory info on this system.")
        elif system == "Windows":
            result = _run("systeminfo | findstr /C:\"Available Physical Memory\" /C:\"Total Physical Memory\"", timeout=20)
            if result.stdout.strip():
                lines.append(result.stdout.strip())
            else:
                lines.append("Could not retrieve memory info on this system.")
        else:
            lines.append(f"Memory info not available on {system}.")

    output = "\n".join(lines)
    return {"output": output, "display": output, "data": data}


def cpu_info() -> Dict[str, Any]:
    """Show CPU information."""
    system = platform.system()
    data: Dict[str, Any] = {"architecture": platform.machine(), "processor": platform.processor()}
    lines: List[str] = []

    if system == "Linux" and os.path.isfile("/proc/cpuinfo"):
        try:
            with open("/proc/cpuinfo", "r") as fh:
                cpuinfo = fh.read()

            processors = cpuinfo.split("\n\n")
            core_count = 0
            for block in processors:
                if "processor" in block:
                    core_count += 1

            data["logical_cores"] = core_count

            # Extract key info from first processor block
            first = processors[0] if processors else ""
            for field in ("model name", "cpu MHz", "cache size", "vendor_id"):
                m = re.search(rf"{field}\s*:\s*(.+)", first)
                if m:
                    key = field.replace(" ", "_")
                    data[key] = m.group(1).strip()

            model = data.get("model_name", "Unknown")
            mhz = data.get("cpu_mhz", "?")
            cache = data.get("cache_size", "?")

            lines = [
                f"CPU Model     : {model}",
                f"Logical Cores : {core_count}",
                f"Clock Speed   : {mhz} MHz",
                f"Cache Size    : {cache}",
                f"Architecture  : {platform.machine()}",
            ]

            # CPU load average
            try:
                load1, load5, load15 = os.getloadavg()
                lines.append(f"Load Average   : {load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)")
                data["load_avg_1m"] = round(load1, 2)
                data["load_avg_5m"] = round(load5, 2)
                data["load_avg_15m"] = round(load15, 2)
            except (OSError, AttributeError):
                pass

        except Exception as exc:
            return {"error": f"Could not read CPU info: {exc}"}
    else:
        # Fallback
        result = _run("sysctl -n machdep.cpu.brand_string 2>/dev/null" if system == "Darwin"
                      else "echo unknown", timeout=5)
        lines.append(f"Processor: {platform.processor() or result.stdout.strip()}")
        lines.append(f"Architecture: {platform.machine()}")

    output = "\n".join(lines)
    return {"output": output, "display": output, "data": data}


def list_processes(
    filter: Optional[str] = None,
    sort_by: Optional[str] = None,
) -> Dict[str, Any]:
    """List running processes with optional filter and sort."""
    result = _run("ps aux --sort=-%mem 2>/dev/null || ps aux", timeout=10)
    if result.returncode != 0:
        return {"error": "Could not list processes."}

    raw_lines = result.stdout.strip().split("\n")
    if not raw_lines:
        return {"output": "(no processes)"}

    # Parse header
    header = raw_lines[0].split()
    # ps aux columns: USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND
    processes: List[Dict[str, str]] = []

    for line in raw_lines[1:]:
        parts = line.split(None, 10)  # Split into max 11 parts
        if len(parts) < 11:
            continue
        proc = {
            "user": parts[0],
            "pid": parts[1],
            "cpu": parts[2],
            "mem": parts[3],
            "vsz": parts[4],
            "rss": parts[5],
            "stat": parts[6],
            "start": parts[7],
            "time": parts[8],
            "command": parts[10] if len(parts) > 10 else "",
        }
        processes.append(proc)

    # Filter
    if filter:
        fl = filter.lower()
        processes = [p for p in processes
                     if fl in p["user"].lower() or fl in p["command"].lower()
                     or fl in p["pid"]]

    # Sort
    if sort_by:
        sort_key = sort_by.lower()
        valid_keys = {"pid", "cpu", "mem", "vsz", "rss", "command", "user"}
        if sort_key in valid_keys:
            reverse = sort_key in ("cpu", "mem", "vsz", "rss")
            processes.sort(key=lambda p: p.get(sort_key, ""), reverse=reverse)

    # Build output (show top 50)
    show = processes[:50]
    lines = [f"{'USER':<12} {'PID':>6} {'%CPU':>6} {'%MEM':>6} {'RSS':>8}  COMMAND"]
    for p in show:
        cmd = p["command"][:60]
        lines.append(f"{p['user']:<12} {p['pid']:>6} {p['cpu']:>6} {p['mem']:>6} {p['rss']:>8}  {cmd}")

    total = len(processes)
    if total > 50:
        lines.append(f"\n... showing 50 of {total} processes")

    output = "\n".join(lines)
    return {
        "output": f"{total} process(es) found" + (f" matching '{filter}'" if filter else ""),
        "display": output,
        "data": {"total": total, "shown": min(total, 50), "processes": show},
    }


def network_info() -> Dict[str, Any]:
    """Show network interfaces and connections."""
    lines: List[str] = []
    data: Dict[str, Any] = {}

    # Interfaces
    ip_result = _run("ip addr 2>/dev/null || ifconfig 2>/dev/null", timeout=10)
    if ip_result.stdout.strip():
        lines.append("=== Network Interfaces ===")
        lines.append(ip_result.stdout.strip())
        lines.append("")

    # Routing table
    route_result = _run("ip route 2>/dev/null || netstat -rn 2>/dev/null", timeout=10)
    if route_result.stdout.strip():
        lines.append("=== Routing Table ===")
        lines.append(route_result.stdout.strip())
        lines.append("")

    # Listening ports
    ss_result = _run("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null", timeout=10)
    if ss_result.stdout.strip():
        lines.append("=== Listening Ports ===")
        lines.append(ss_result.stdout.strip())

    output = "\n".join(lines)
    return {
        "output": output,
        "display": output,
        "data": data,
    }


def port_check(port: int) -> Dict[str, Any]:
    """Check what process is using a specific port."""
    if not (0 < port <= 65535):
        return {"error": f"Invalid port number: {port}. Must be 1-65535."}

    # Try lsof first
    result = _run(f"lsof -i :{port} 2>/dev/null", timeout=10)
    if result.stdout.strip():
        return {
            "output": f"Port {port} is in use:",
            "display": result.stdout.strip(),
            "data": {"port": port, "in_use": True},
        }

    # Fallback: ss
    ss_result = _run(f"ss -tlnp 2>/dev/null | grep ':{port} '", timeout=10)
    if ss_result.stdout.strip():
        return {
            "output": f"Port {port} is in use:",
            "display": ss_result.stdout.strip(),
            "data": {"port": port, "in_use": True},
        }

    return {
        "output": f"Port {port} is not in use.",
        "data": {"port": port, "in_use": False},
    }


def system_info() -> Dict[str, Any]:
    """Return general system information."""
    info: Dict[str, Any] = {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "processor": platform.processor(),
    }

    lines: List[str] = []

    # OS details
    if platform.system() == "Linux":
        try:
            with open("/etc/os-release", "r") as fh:
                for raw in fh:
                    if raw.startswith("PRETTY_NAME="):
                        info["distro"] = raw.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass

    lines.append(f"OS           : {info.get('distro', platform.system())}")
    lines.append(f"Kernel       : {platform.release()}")
    lines.append(f"Architecture : {platform.machine()}")
    lines.append(f"Hostname     : {platform.node()}")
    lines.append(f"Python       : {platform.python_version()}")

    # Uptime
    if platform.system() == "Linux":
        uptime_result = _run("uptime -p 2>/dev/null", timeout=5)
        if uptime_result.stdout.strip():
            lines.append(f"Uptime       : {uptime_result.stdout.strip()}")
        else:
            try:
                with open("/proc/uptime", "r") as fh:
                    secs = float(fh.read().split()[0])
                    days = int(secs // 86400)
                    hours = int((secs % 86400) // 3600)
                    mins = int((secs % 3600) // 60)
                    lines.append(f"Uptime       : {days}d {hours}h {mins}m")
            except Exception:
                pass

    # Current shell
    shell = os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown"))
    lines.append(f"Shell        : {shell}")

    # Current user
    import getpass
    lines.append(f"User         : {getpass.getuser()}")
    info["user"] = getpass.getuser()
    info["shell"] = shell

    output = "\n".join(lines)
    return {"output": output, "display": output, "data": info}


def install_package(package: str, upgrade: bool = False) -> Dict[str, Any]:
    """Install a Python package via pip."""
    if not package or not package.strip():
        return {"error": "No package name provided."}

    # Sanitize: only allow valid package names
    pkg = package.strip()
    if re.search(r"[;&|`$]", pkg):
        return {"error": "Invalid package name."}

    flag = "--upgrade" if upgrade else ""
    cmd = f"{sys.executable} -m pip install {pkg} {flag} --quiet 2>&1"

    result = _run(cmd, timeout=120)
    if result.returncode == 0:
        return {
            "output": f"Package '{pkg}' installed successfully.",
            "data": {"package": pkg, "upgrade": upgrade, "success": True},
        }
    else:
        return {
            "output": f"Failed to install '{pkg}'.",
            "error": result.stderr or result.stdout,
            "data": {"package": pkg, "success": False},
        }


def check_service(name: str) -> Dict[str, Any]:
    """Check if a service or process is running."""
    if not name or not name.strip():
        return {"error": "No service name provided."}

    # Try systemctl first
    systemctl_result = _run(f"systemctl is-active {name} 2>/dev/null", timeout=5)
    if systemctl_result.stdout.strip() in ("active", "inactive", "failed", "activating"):
        status = systemctl_result.stdout.strip()
        running = status == "active"

        # Get more details
        status_result = _run(f"systemctl status {name} --no-pager -l 2>/dev/null | head -20", timeout=5)
        details = status_result.stdout.strip() if status_result.stdout.strip() else ""

        output = f"Service '{name}': {status.upper()}"
        if details:
            output += f"\n\n{details}"

        return {
            "output": output,
            "display": details,
            "data": {"name": name, "status": status, "running": running},
        }

    # Fallback: pgrep
    pgrep_result = _run(f"pgrep -f '{name}' 2>/dev/null", timeout=5)
    pids = [p for p in pgrep_result.stdout.strip().split("\n") if p.strip()]
    running = len(pids) > 0

    if running:
        # Get details
        ps_result = _run(f"ps -p {','.join(pids[:5])} -o pid,user,%cpu,%mem,command --no-headers 2>/dev/null", timeout=5)
        details = ps_result.stdout.strip() if ps_result.stdout.strip() else ""

        output = f"Process '{name}': RUNNING ({len(pids)} process(es))"
        if details:
            output += f"\n\n{details}"
    else:
        output = f"Process '{name}': NOT RUNNING"
        details = ""

    return {
        "output": output,
        "display": details,
        "data": {"name": name, "running": running, "pids": pids if running else []},
    }


# Need sys for install_package
import sys


# =====================================================================
# Registration
# =====================================================================

_SYSTEM_TOOLS = [
    (
        "disk_usage",
        "Show disk usage for a path, including a breakdown of top-level directories.",
        [
            ToolParameter("path", "string", "Path to check", required=False, default="/"),
        ],
        disk_usage,
        False,
    ),
    (
        "memory_info",
        "Show system memory (RAM and swap) usage information.",
        [],
        memory_info,
        False,
    ),
    (
        "cpu_info",
        "Show CPU information including model, core count, speed, and load average.",
        [],
        cpu_info,
        False,
    ),
    (
        "list_processes",
        "List running processes. Can filter by name and sort by various fields.",
        [
            ToolParameter("filter", "string", "Filter processes by name or PID substring", required=False, default=None),
            ToolParameter("sort_by", "string", "Sort field (pid, cpu, mem, vsz, rss, command)", required=False, default=None),
        ],
        list_processes,
        False,
    ),
    (
        "network_info",
        "Show network interfaces, routing table, and listening ports.",
        [],
        network_info,
        False,
    ),
    (
        "port_check",
        "Check what process is listening on a specific port.",
        [
            ToolParameter("port", "integer", "Port number (1-65535)"),
        ],
        port_check,
        False,
    ),
    (
        "system_info",
        "Show general system information: OS, kernel, hostname, uptime, shell.",
        [],
        system_info,
        False,
    ),
    (
        "install_package",
        "Install a Python package via pip.",
        [
            ToolParameter("package", "string", "Package name to install"),
            ToolParameter("upgrade", "boolean", "Upgrade if already installed", required=False, default=False),
        ],
        install_package,
        True,
    ),
    (
        "check_service",
        "Check if a systemd service or process is running.",
        [
            ToolParameter("name", "string", "Service or process name"),
        ],
        check_service,
        False,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all system tools with the given registry."""
    for name, desc, params, func, dangerous in _SYSTEM_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
