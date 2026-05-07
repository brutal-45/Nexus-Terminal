"""Workspace awareness for Nexus.

Detects the user's environment at startup — operating system, project type,
available tools, environment variables, etc. — and surfaces the information
through a simple dict API.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Common environment variable names that may contain secrets
_SENSITIVE_ENV_PATTERN = re.compile(
    r"(?i)"
    r"(key|secret|token|password|passwd|credential|auth|private|session)"
)


class Workspace:
    """Detects and caches workspace metadata.

    Usage::

        ws = Workspace()
        ws.detect()
        print(ws.info["os"])
        print(ws.summary())
    """

    def __init__(self, working_dir: Optional[str] = ".") -> None:
        self.working_dir = Path(working_dir).expanduser().resolve()
        self.info: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self) -> Dict[str, Any]:
        """Gather all workspace information and return it.

        Populates :attr:`info` and returns the same dict.
        """
        self.info = {
            "cwd": self._detect_cwd(),
            "home": self._detect_home(),
            "user": self._detect_user(),
            "hostname": self._detect_hostname(),
            "os": self._detect_os(),
            "kernel": self._detect_kernel(),
            "arch": self._detect_arch(),
            "shell": self._detect_shell(),
            "python_version": self._detect_python_version(),
            "git_version": self._detect_git_version(),
            "python_packages": self._detect_python_packages(),
            "project_type": self._detect_project_type(),
            "project_name": self._detect_project_name(),
            "env_vars": self._detect_safe_env_vars(),
        }
        return self.info

    # ------------------------------------------------------------------
    # Individual detectors (kept private)
    # ------------------------------------------------------------------

    def _detect_cwd(self) -> str:
        """Return the current working directory."""
        try:
            return str(self.working_dir.resolve())
        except OSError:
            return os.getcwd()

    @staticmethod
    def _detect_home() -> str:
        """Return the user's home directory."""
        return str(Path.home())

    @staticmethod
    def _detect_user() -> str:
        """Return the username."""
        try:
            return os.getlogin()
        except (OSError, AttributeError):
            return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))

    @staticmethod
    def _detect_hostname() -> str:
        """Return the machine hostname."""
        try:
            return platform.node()
        except Exception:
            return "unknown"

    @staticmethod
    def _detect_os() -> str:
        """Return a human-readable OS string."""
        system = platform.system()
        if system == "Linux":
            try:
                # Try /etc/os-release for a friendly distro name
                os_release = Path("/etc/os-release")
                if os_release.exists():
                    import configparser
                    cp = configparser.ConfigParser()
                    cp.read_string(f"[section]\n{os_release.read_text()}")
                    name = cp.get("section", "PRETTY_NAME", fallback="")
                    if name:
                        return name
            except Exception:
                pass
            return f"{system} (kernel {platform.release()})"
        if system == "Darwin":
            return f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else "macOS"
        if system == "Windows":
            ver = platform.win32_ver()
            return f"Windows {ver[1]}" if ver[1] else "Windows"
        return system

    @staticmethod
    def _detect_kernel() -> str:
        """Return the kernel version."""
        return platform.release()

    @staticmethod
    def _detect_arch() -> str:
        """Return the system architecture."""
        machine = platform.machine()
        if machine == "x86_64":
            return "x86_64 (amd64)"
        if machine == "aarch64":
            return "ARM64 (aarch64)"
        if machine == "arm64":
            return "ARM64"
        return machine or "unknown"

    @staticmethod
    def _detect_shell() -> str:
        """Return the user's default shell."""
        shell = os.environ.get("SHELL", "")
        if shell:
            return shell

        # Windows fallback
        if platform.system() == "Windows":
            return os.environ.get("COMSPEC", "cmd.exe")

        # Try to detect from passwd
        try:
            import pwd
            entry = pwd.getpwuid(os.getuid())
            return entry.pw_shell
        except Exception:
            return ""

    @staticmethod
    def _detect_python_version() -> str:
        """Return the Python version string."""
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    @staticmethod
    def _detect_git_version() -> Optional[str]:
        """Return the installed Git version, or None if not available."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        return None

    @staticmethod
    def _detect_python_packages() -> List[str]:
        """Detect a curated list of key installed Python packages."""
        packages: List[str] = []
        key_packages = [
            "numpy", "pandas", "requests", "flask", "django",
            "fastapi", "uvicorn", "pytest", "black", "ruff",
            "mypy", "pylint", "sphinx", "click", "typer",
            "rich", "httpx", "aiohttp", "sqlalchemy", "pillow",
            "scipy", "scikit-learn", "torch", "tensorflow",
            "matplotlib", "plotly", "docker", "boto3",
        ]

        for pkg in key_packages:
            try:
                __import__(pkg)
                packages.append(pkg)
            except ImportError:
                pass

        return sorted(packages)

    def _detect_project_type(self) -> str:
        """Detect the project type based on files in the working directory."""
        cwd = self.working_dir

        project_markers: Dict[str, List[str]] = {
            "Python": [
                "setup.py", "setup.cfg", "pyproject.toml",
                "requirements.txt", "Pipfile", "poetry.lock",
                ".python-version", "noxfile.py", "tox.ini",
                "MANIFEST.in",
            ],
            "JavaScript/TypeScript": [
                "package.json", ".nvmrc", "tsconfig.json",
                ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
                "next.config.js", "next.config.mjs", "next.config.ts",
                "vite.config.ts", "vite.config.js",
                "webpack.config.js", "rollup.config.js",
            ],
            "Rust": [
                "Cargo.toml", "Cargo.lock",
            ],
            "Go": [
                "go.mod", "go.sum",
            ],
            "Java/Kotlin": [
                "pom.xml", "build.gradle", "build.gradle.kts",
                "settings.gradle", ".gradle",
            ],
            "Ruby": [
                "Gemfile", "Rakefile", ".ruby-version",
                "gemspec", "*.gemspec",
            ],
            "PHP": [
                "composer.json", "artisan",
            ],
            "C/C++": [
                "CMakeLists.txt", "Makefile", "configure.ac",
                "meson.build",
            ],
            "Swift": [
                "Package.swift", "*.xcodeproj",
            ],
            "Docker": [
                "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
            ],
        }

        for proj_type, markers in project_markers.items():
            for marker in markers:
                if "*" in marker:
                    # Glob pattern
                    if any(cwd.glob(marker)):
                        return proj_type
                else:
                    if (cwd / marker).exists():
                        return proj_type

        return "Unknown"

    def _detect_project_name(self) -> str:
        """Detect the project name from directory or config files."""
        cwd = self.working_dir

        # Try package.json
        pkg_json = cwd / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                name = data.get("name")
                if name and isinstance(name, str):
                    return name
            except Exception:
                pass

        # Try pyproject.toml (basic parsing — look for [project] name = "...")
        pyproject = cwd / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8")
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Try setup.py
        setup_py = cwd / "setup.py"
        if setup_py.exists():
            try:
                content = setup_py.read_text(encoding="utf-8")
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Try Cargo.toml
        cargo = cwd / "Cargo.toml"
        if cargo.exists():
            try:
                content = cargo.read_text(encoding="utf-8")
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
            except Exception:
                pass

        # Fall back to directory name
        return cwd.name

    @staticmethod
    def _detect_safe_env_vars() -> Dict[str, str]:
        """Return non-sensitive environment variables."""
        safe_keys = {
            "PATH", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TERM",
            "SHELL", "HOME", "USER", "LOGNAME", "HOSTNAME", "HOSTTYPE",
            "OSTYPE", "MACHTYPE", "EDITOR", "VISUAL", "PAGER", "TERM_PROGRAM",
            "COLORTERM", "COLORFGBG", "DISPLAY", "XDG_SESSION_TYPE",
            "XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "WAYLAND_DISPLAY",
            "TZ", "LOCALE", "OMP_THEME", "VIRTUAL_ENV", "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV", "POETRY_VIRTUALENVS_IN_PROJECT",
            "NVM_DIR", "PYENV_SHELL", "GOPATH", "GOROOT", "CARGO_HOME",
            "RUSTUP_HOME", "NODE_PATH", "JAVA_HOME",
        }

        result: Dict[str, str] = {}
        for key in sorted(os.environ):
            if key in safe_keys:
                result[key] = os.environ[key]

        return result

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_dangerous_env_vars() -> List[str]:
        """Detect environment variables that may contain sensitive values.

        Returns:
            A list of variable names that match common secret patterns.
        """
        dangerous: List[str] = []
        for key in os.environ:
            if _SENSITIVE_ENV_PATTERN.search(key):
                dangerous.append(key)
        return sorted(dangerous)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Return a formatted multi-line summary of the workspace.

        Intended for display in the welcome banner or help output.
        """
        if not self.info:
            self.detect()

        lines: List[str] = []
        lines.append(f"Workspace: {self.info.get('cwd', 'unknown')}")
        lines.append(f"OS: {self.info.get('os', 'unknown')}")

        kernel = self.info.get("kernel", "")
        if kernel:
            lines.append(f"Kernel: {kernel}")

        lines.append(f"Architecture: {self.info.get('arch', 'unknown')}")
        lines.append(f"User: {self.info.get('user', 'unknown')}")

        shell = self.info.get("shell", "")
        if shell:
            lines.append(f"Shell: {shell}")

        lines.append(f"Python: {self.info.get('python_version', 'unknown')}")

        git = self.info.get("git_version", "")
        if git:
            lines.append(f"Git: {git}")

        proj_type = self.info.get("project_type", "Unknown")
        proj_name = self.info.get("project_name", "")
        if proj_name:
            lines.append(f"Project: {proj_name} ({proj_type})")
        elif proj_type != "Unknown":
            lines.append(f"Project type: {proj_type}")

        packages = self.info.get("python_packages", [])
        if packages:
            lines.append(f"Key Python packages: {', '.join(packages[:8])}")
            if len(packages) > 8:
                lines.append(f"  … and {len(packages) - 8} more")

        # Warn about sensitive env vars
        dangerous = self.get_dangerous_env_vars()
        if dangerous:
            lines.append(
                f"⚠ Detected {len(dangerous)} sensitive environment variable(s). "
                "Nexus will redact their values in output."
            )

        return "\n".join(lines)
