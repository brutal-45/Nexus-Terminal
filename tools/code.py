"""Code analysis and development tools."""

import ast
import os
import re
import subprocess
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Helpers
# =====================================================================

def _resolve(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _read_text(path: str) -> Optional[str]:
    """Read a text file, return content or None on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return None


def _detect_language(path: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".jsx": "React JSX",
        ".tsx": "React TSX",
        ".rb": "Ruby",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".kt": "Kotlin",
        ".c": "C",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".h": "C/C++ Header",
        ".hpp": "C++ Header",
        ".cs": "C#",
        ".php": "PHP",
        ".swift": "Swift",
        ".m": "Objective-C",
        ".r": "R",
        ".R": "R",
        ".lua": "Lua",
        ".pl": "Perl",
        ".sh": "Shell",
        ".bash": "Shell",
        ".zsh": "Shell",
        ".ps1": "PowerShell",
        ".sql": "SQL",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".less": "LESS",
        ".json": "JSON",
        ".xml": "XML",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".toml": "TOML",
        ".md": "Markdown",
        ".txt": "Plain Text",
        ".csv": "CSV",
    }
    return mapping.get(ext, ext if ext else "Unknown")


# =====================================================================
# Tool implementations
# =====================================================================

def analyze_code(path: str) -> Dict[str, Any]:
    """Analyze a code file: language, lines, functions, classes, imports, complexity."""
    path = _resolve(path)
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    content = _read_text(path)
    if content is None:
        return {"error": f"Could not read file: {path}"}

    language = _detect_language(path)
    lines = content.split("\n")
    total_lines = len(lines)
    blank_lines = sum(1 for l in lines if not l.strip())
    comment_lines = 0
    code_lines = 0

    info: Dict[str, Any] = {
        "path": path,
        "language": language,
        "total_lines": total_lines,
        "blank_lines": blank_lines,
    }

    # Language-specific analysis
    if language == "Python":
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None

        functions = []
        classes = []
        imports = []
        decorators = set()

        if tree:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Count non-blank, non-comment lines in the function
                    func_lines = node.end_lineno - node.lineno + 1 if hasattr(node, "end_lineno") else "?"
                    functions.append({
                        "name": node.name,
                        "line": node.lineno,
                        "args": len(node.args.args),
                        "lines": func_lines,
                    })
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Name):
                            decorators.add(dec.id)
                        elif isinstance(dec, ast.Attribute):
                            decorators.add(dec.attr)
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        "name": node.name,
                        "line": node.lineno,
                        "methods": sum(1 for n in ast.walk(node) if isinstance(n, ast.FunctionDef)),
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        imports.append(f"{module}.{alias.name}")

            info["functions"] = functions
            info["classes"] = classes
            info["imports"] = imports
            info["decorators"] = sorted(decorators)

        # Count comment lines and code lines
        in_multiline_string = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if in_multiline_string:
                comment_lines += 1
                if '"""' in stripped or "'''" in stripped:
                    triple = '"""' if '"""' in stripped else "'''"
                    count = stripped.count(triple)
                    if count >= 2:
                        in_multiline_string = False
                continue
            if stripped.startswith("#"):
                comment_lines += 1
            elif '"""' in stripped or "'''" in stripped:
                comment_lines += 1
                triple = '"""' if '"""' in stripped else "'''"
                count = stripped.count(triple)
                if count == 1:
                    in_multiline_string = True
            else:
                code_lines += 1
    else:
        # Generic analysis for non-Python files
        comment_chars = {"//": ["JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Rust", "PHP"],
                         "#": ["Ruby", "Shell", "PowerShell", "YAML", "TOML"],
                         "--": ["SQL", "Lua"]}
        single_comment = "//"
        for marker, langs in comment_chars.items():
            if language in langs:
                single_comment = marker
                break

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(single_comment):
                comment_lines += 1
            elif stripped.startswith("/*") or stripped.startswith("*"):
                comment_lines += 1
            else:
                code_lines += 1

        # Regex for functions and classes in common languages
        func_pattern = r"^\s*(def|function|func|fn|sub|func )\s+(\w+)"
        class_pattern = r"^\s*(class|struct|interface|type)\s+(\w+)"

        functions = []
        classes = []
        for i, line in enumerate(lines, 1):
            fm = re.match(func_pattern, line)
            if fm:
                functions.append({"name": fm.group(2), "line": i})
            cm = re.match(class_pattern, line)
            if cm:
                classes.append({"name": cm.group(2), "line": i})

        info["functions"] = functions
        info["classes"] = classes

    info["comment_lines"] = comment_lines
    info["code_lines"] = code_lines

    # Build display
    disp = [f"File      : {path}",
            f"Language  : {language}",
            f"Lines     : {total_lines} total, {code_lines} code, {comment_lines} comments, {blank_lines} blank"]

    if info.get("functions"):
        disp.append(f"\nFunctions ({len(info['functions'])}):")
        for f in info["functions"][:30]:
            args = f.get("args", "?")
            flines = f.get("lines", "?")
            if isinstance(flines, int):
                disp.append(f"  L{f['line']:>5} : {f['name']}({args} args, {flines} lines)")
            else:
                disp.append(f"  L{f['line']:>5} : {f['name']}")

    if info.get("classes"):
        disp.append(f"\nClasses ({len(info['classes'])}):")
        for c in info["classes"][:20]:
            methods = c.get("methods", "?")
            disp.append(f"  L{c['line']:>5} : {c['name']} ({methods} methods)")

    if info.get("imports"):
        disp.append(f"\nImports ({len(info['imports'])}):")
        for imp in info["imports"][:20]:
            disp.append(f"  {imp}")

    if info.get("decorators"):
        disp.append(f"\nDecorators: {', '.join(info['decorators'])}")

    output = "\n".join(disp)
    return {"output": output, "display": output, "data": info}


def explain_code(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> Dict[str, Any]:
    """Return code content formatted for the LLM to explain."""
    path = _resolve(path)
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    content = _read_text(path)
    if content is None:
        return {"error": f"Could not read file: {path}"}

    lines = content.split("\n")
    total = len(lines)

    s = (start_line - 1) if start_line else 0
    s = max(0, s)
    e = end_line if end_line else total
    e = min(e, total)

    selected = lines[s:e]
    language = _detect_language(path)

    numbered = []
    for i, line in enumerate(selected, start=s + 1):
        numbered.append(f"{i:>6} | {line}")

    code_text = "\n".join(numbered)

    header = [
        f"File: {path}",
        f"Language: {language}",
        f"Lines: {s + 1}–{e} of {total}",
        "",
        "```" + _lang_alias(language),
        code_text,
        "```",
    ]

    output = "\n".join(header)
    return {
        "output": output,
        "display": output,
        "data": {"path": path, "language": language, "start": s + 1, "end": e, "total": total},
    }


def _lang_alias(language: str) -> str:
    """Return a common syntax-highlighting alias for the language."""
    aliases = {
        "Python": "python", "JavaScript": "javascript", "TypeScript": "typescript",
        "React JSX": "jsx", "React TSX": "tsx", "Ruby": "ruby", "Go": "go",
        "Rust": "rust", "Java": "java", "Kotlin": "kotlin", "C": "c",
        "C++": "cpp", "C#": "csharp", "PHP": "php", "Swift": "swift",
        "Shell": "bash", "PowerShell": "powershell", "SQL": "sql",
        "HTML": "html", "CSS": "css", "SCSS": "scss", "JSON": "json",
        "XML": "xml", "YAML": "yaml", "TOML": "toml", "Markdown": "markdown",
    }
    return aliases.get(language, "")


def run_tests(path: str, args: Optional[str] = None) -> Dict[str, Any]:
    """Run test files using pytest or unittest."""
    path = _resolve(path)
    if not os.path.exists(path):
        return {"error": f"Path not found: {path}"}

    # Determine test runner
    extra_args = args or ""
    commands = []

    if os.path.isfile(path):
        # Single file
        commands = [
            f"{sys.executable} -m pytest {path} -v {extra_args}",
            f"{sys.executable} -m unittest {path} -v {extra_args}",
        ]
    else:
        # Directory
        commands = [
            f"{sys.executable} -m pytest {path} -v {extra_args}",
            f"{sys.executable} -m pytest discover -s {path} -v {extra_args}",
            f"{sys.executable} -m unittest discover -s {path} -v {extra_args}",
        ]

    last_error = ""
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                output = result.stdout or "(tests passed with no output)"
                return {
                    "output": output,
                    "display": output,
                    "data": {"command": cmd, "passed": True},
                }
            last_error = result.stdout + "\n" + result.stderr
        except subprocess.TimeoutExpired:
            last_error = f"Tests timed out: {cmd}"
        except Exception as exc:
            last_error = str(exc)

    # If no command succeeded, return last output
    return {
        "output": last_error,
        "error": "Tests did not pass.",
        "data": {"passed": False},
    }


def lint_code(path: str) -> Dict[str, Any]:
    """Perform basic code linting: check for common issues."""
    path = _resolve(path)
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    content = _read_text(path)
    if content is None:
        return {"error": f"Could not read file: {path}"}

    language = _detect_language(path)
    lines = content.split("\n")
    issues: List[Dict[str, Any]] = []

    if language == "Python":
        # Check for long lines
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append({"line": i, "type": "style", "message": f"Line too long ({len(line)} chars, max 120)"})

        # Check for trailing whitespace
        for i, line in enumerate(lines, 1):
            if line != line.rstrip() and line.strip():
                issues.append({"line": i, "type": "style", "message": "Trailing whitespace"})

        # Check for missing newline at end of file
        if content and not content.endswith("\n"):
            issues.append({"line": len(lines), "type": "style", "message": "No newline at end of file"})

        # Try AST-based checks
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            issues.append({"line": exc.lineno or 0, "type": "error", "message": f"Syntax error: {exc.msg}"})
            tree = None

        if tree:
            # Unused imports (simple heuristic: imported but never used in the file)
            used_names: set = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used_names.add(node.value.id if isinstance(node.value, ast.Name) else "")

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        # Strip submodule: `os.path` → check for `os`
                        base = name.split(".")[0]
                        if base not in used_names:
                            issues.append({"line": node.lineno, "type": "warning",
                                           "message": f"Potentially unused import: {alias.name}"})
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if name not in used_names:
                            issues.append({"line": node.lineno, "type": "warning",
                                           "message": f"Potentially unused import: {name}"})

            # Functions without docstrings
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not (node.body and isinstance(node.body[0], ast.Expr)
                            and isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                        issues.append({"line": node.lineno, "type": "info",
                                       "message": f"Function '{node.name}' has no docstring"})

            # Classes without docstrings
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if not (node.body and isinstance(node.body[0], ast.Expr)
                            and isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                        issues.append({"line": node.lineno, "type": "info",
                                       "message": f"Class '{node.name}' has no docstring"})
    else:
        # Generic linting for other languages
        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append({"line": i, "type": "style", "message": f"Line too long ({len(line)} chars)"})
            if line != line.rstrip() and line.strip():
                issues.append({"line": i, "type": "style", "message": "Trailing whitespace"})

        # TODO lines
        for i, line in enumerate(lines, 1):
            if re.search(r"\bTODO\b", line, re.IGNORECASE):
                issues.append({"line": i, "type": "info", "message": f"TODO found: {line.strip()[:80]}"})

    if not issues:
        return {
            "output": f"No issues found in {path}",
            "data": {"path": path, "issues": [], "language": language},
        }

    disp_lines = [f"Lint results for {path} ({language}):"]
    disp_lines.append(f"Found {len(issues)} issue(s)\n")

    # Group by severity
    for sev in ("error", "warning", "style", "info"):
        sev_issues = [i for i in issues if i["type"] == sev]
        if sev_issues:
            disp_lines.append(f"[{sev.upper()}] ({len(sev_issues)})")
            for iss in sev_issues[:50]:
                disp_lines.append(f"  L{iss['line']:>5} : {iss['message']}")
            disp_lines.append("")

    output = "\n".join(disp_lines)
    return {
        "output": output,
        "display": output,
        "data": {"path": path, "issues": issues, "language": language,
                 "summary": Counter(i["type"] for i in issues)},
    }


def count_lines(path: str, by_language: bool = True) -> Dict[str, Any]:
    """Count lines of code in a file or directory."""
    path = _resolve(path)
    if not os.path.exists(path):
        return {"error": f"Path not found: {path}"}

    ext_map: Counter = Counter()
    total_code = 0
    total_blank = 0
    total_comment = 0
    file_count = 0

    comment_prefixes = {
        ".py": "#", ".sh": "#", ".bash": "#", ".zsh": "#", ".ps1": "#",
        ".rb": "#", ".r": "#", ".yaml": "#", ".yml": "#", ".toml": "#",
        ".js": "//", ".ts": "//", ".jsx": "//", ".tsx": "//",
        ".java": "//", ".kt": "//", ".c": "//", ".cpp": "//", ".cc": "//",
        ".h": "//", ".hpp": "//", ".cs": "//", ".go": "//", ".rs": "//",
        ".swift": "//", ".php": "//", ".sql": "--", ".lua": "--",
        ".pl": "#",
    }

    text_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs", ".java",
        ".kt", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".cs", ".php",
        ".swift", ".m", ".r", ".R", ".lua", ".pl", ".sh", ".bash", ".zsh",
        ".ps1", ".sql", ".html", ".css", ".scss", ".less", ".json", ".xml",
        ".yaml", ".yml", ".toml", ".md", ".txt", ".csv", ".vim", ".el",
        ".cljs", ".ex", ".exs", ".hs", ".ml", ".lisp", ".scala", ".clj",
        ".dart", ".vue", ".svelte", ".graphql", ".proto", ".tf", ".hcl",
    }

    def _count_file(filepath: str) -> None:
        nonlocal total_code, total_blank, total_comment, file_count
        ext = os.path.splitext(filepath)[1].lower()
        if ext and ext not in text_extensions:
            return

        content = _read_text(filepath)
        if content is None:
            return

        file_count += 1
        comment_char = comment_prefixes.get(ext, "//")
        f_code = 0
        f_blank = 0
        f_comment = 0

        in_multiline = False
        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                f_blank += 1
                continue
            if in_multiline:
                f_comment += 1
                if ('"""' in stripped or "'''" in stripped) and ext == ".py":
                    triple = '"""' if '"""' in stripped else "'''"
                    if stripped.count(triple) >= 2:
                        in_multiline = False
                elif "*/" in stripped:
                    in_multiline = False
                continue
            if stripped.startswith(comment_char):
                f_comment += 1
            elif stripped.startswith("/*") or (stripped.startswith("*") and ext in (".css", ".scss")):
                f_comment += 1
                if "*/" not in stripped[2:]:
                    in_multiline = True
            elif ext == ".py" and ('"""' in stripped or "'''" in stripped):
                f_comment += 1
                triple = '"""' if '"""' in stripped else "'''"
                if stripped.count(triple) == 1:
                    in_multiline = True
            else:
                f_code += 1

        total_code += f_code
        total_blank += f_blank
        total_comment += f_comment
        ext_map[ext or "(none)"] += (f_code + f_comment + f_blank)

    if os.path.isfile(path):
        _count_file(path)
    else:
        for root, dirs, files in os.walk(path):
            # Skip common non-code directories
            dirs[:] = [d for d in dirs if d not in (
                "__pycache__", ".git", ".svn", "node_modules", "venv",
                ".venv", ".tox", ".eggs", "dist", "build", ".mypy_cache",
                ".pytest_cache", ".next", ".nuxt", "target", "vendor",
            )]
            for f in sorted(files):
                _count_file(os.path.join(root, f))

    lines_out = [
        f"Path      : {path}",
        f"Files     : {file_count}",
        f"Code      : {total_code} lines",
        f"Comment   : {total_comment} lines",
        f"Blank     : {total_blank} lines",
        f"Total     : {total_code + total_comment + total_blank} lines",
    ]

    if by_language and ext_map:
        lines_out.append(f"\nBy language:")
        for ext, count in ext_map.most_common(20):
            pct = count / max(total_code + total_comment + total_blank, 1) * 100
            lines_out.append(f"  {ext:<12} {count:>8} lines ({pct:.1f}%)")

    output = "\n".join(lines_out)
    return {
        "output": output,
        "display": output,
        "data": {
            "path": path,
            "files": file_count,
            "code_lines": total_code,
            "comment_lines": total_comment,
            "blank_lines": total_blank,
            "total_lines": total_code + total_comment + total_blank,
            "by_extension": dict(ext_map),
        },
    }


def find_definitions(
    path: str,
    name_pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """Find class and function definitions in code files."""
    path = _resolve(path)
    if not os.path.exists(path):
        return {"error": f"Path not found: {path}"}

    definitions: List[Dict[str, Any]] = []
    text_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".rb", ".go", ".rs", ".java",
        ".kt", ".c", ".cpp", ".cc", ".h", ".hpp", ".cs", ".php", ".swift",
        ".sh", ".bash", ".lua", ".pl", ".sql", ".r", ".ex", ".exs",
        ".hs", ".scala", ".dart", ".vue", ".svelte",
    }

    # Patterns for various languages
    patterns = {
        ".py": [
            (r"^\s*(class)\s+([\w.]+)", "class"),
            (r"^\s*(async\s+def|def)\s+([\w.]+)", "function"),
        ],
    }
    generic_func = r"^\s*(function|func|fn|def|sub|proc)\s+([\w.]+)"
    generic_class = r"^\s*(class|struct|interface|trait|enum|type)\s+([\w.]+)"

    def _scan_file(filepath: str) -> None:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in text_extensions:
            return

        content = _read_text(filepath)
        if content is None:
            return

        rel = os.path.relpath(filepath, path)

        ext_patterns = patterns.get(ext)
        if ext_patterns:
            for line in content.split("\n"):
                for pat, kind in ext_patterns:
                    m = re.match(pat, line)
                    if m:
                        name = m.group(2)
                        if name_pattern and name_pattern.lower() not in name.lower():
                            continue
                        definitions.append({
                            "file": rel,
                            "type": kind,
                            "name": name,
                            "line": content[:content.index(line)].count("\n") + 1,
                            "preview": line.strip()[:100],
                        })
        else:
            for line in content.split("\n"):
                lineno = content[:content.index(line)].count("\n") + 1
                for pat, kind in [(generic_func, "function"), (generic_class, "class")]:
                    m = re.match(pat, line)
                    if m:
                        name = m.group(2)
                        if name_pattern and name_pattern.lower() not in name.lower():
                            continue
                        definitions.append({
                            "file": rel,
                            "type": kind,
                            "name": name,
                            "line": lineno,
                            "preview": line.strip()[:100],
                        })

    if os.path.isfile(path):
        _scan_file(path)
    else:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in (
                "__pycache__", ".git", "node_modules", "venv", ".venv",
                "dist", "build", "target", ".next", ".mypy_cache",
            )]
            for f in sorted(files):
                _scan_file(os.path.join(root, f))

    if not definitions:
        msg = f"No definitions found" + (f" matching '{name_pattern}'" if name_pattern else "")
        return {"output": msg, "data": {"definitions": [], "count": 0}}

    # Group by file
    by_file: Dict[str, list] = {}
    for d in definitions:
        by_file.setdefault(d["file"], []).append(d)

    lines_out = [f"Found {len(definitions)} definition(s)" +
                 (f" matching '{name_pattern}'" if name_pattern else "")]
    for fpath, defs in sorted(by_file.items()):
        lines_out.append(f"\n{fpath}:")
        for d in sorted(defs, key=lambda x: x["line"]):
            icon = "●" if d["type"] == "class" else "○"
            lines_out.append(f"  L{d['line']:>5}  {icon} {d['type']:<8} {d['name']}")

    output = "\n".join(lines_out)
    return {
        "output": output,
        "display": output,
        "data": {"definitions": definitions, "count": len(definitions), "by_file": by_file},
    }


# =====================================================================
# Registration
# =====================================================================

_CODE_TOOLS = [
    (
        "analyze_code",
        "Analyze a code file: detect language, count lines/functions/classes, "
        "show imports, and assess basic complexity.",
        [
            ToolParameter("path", "string", "Path to the code file"),
        ],
        analyze_code,
        False,
    ),
    (
        "explain_code",
        "Return code content formatted for explanation. Optionally limit to a range of lines.",
        [
            ToolParameter("path", "string", "Path to the code file"),
            ToolParameter("start_line", "integer", "Starting line number (1-based)", required=False, default=None),
            ToolParameter("end_line", "integer", "Ending line number (1-based)", required=False, default=None),
        ],
        explain_code,
        False,
    ),
    (
        "run_tests",
        "Run test files using pytest or unittest. Works on single files or directories.",
        [
            ToolParameter("path", "string", "Path to test file or directory"),
            ToolParameter("args", "string", "Additional arguments for the test runner", required=False, default=None),
        ],
        run_tests,
        False,
    ),
    (
        "lint_code",
        "Perform basic code linting: check for long lines, trailing whitespace, "
        "unused imports (Python), missing docstrings, and more.",
        [
            ToolParameter("path", "string", "Path to the code file"),
        ],
        lint_code,
        False,
    ),
    (
        "count_lines",
        "Count lines of code in a file or directory. Can break down by language/extension.",
        [
            ToolParameter("path", "string", "Path to file or directory"),
            ToolParameter("by_language", "boolean", "Break down counts by file extension/language", required=False, default=True),
        ],
        count_lines,
        False,
    ),
    (
        "find_definitions",
        "Find class and function definitions in code files. Supports filtering by name pattern.",
        [
            ToolParameter("path", "string", "Path to file or directory"),
            ToolParameter("name_pattern", "string", "Filter definitions by name substring", required=False, default=None),
        ],
        find_definitions,
        False,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all code tools with the given registry."""
    for name, desc, params, func, dangerous in _CODE_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
