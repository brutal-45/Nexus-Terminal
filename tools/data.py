"""Data parsing, conversion, and analysis tools."""

import csv
import io
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Union
from collections import Counter

from nexus.tools.base import FunctionTool, ToolParameter
from nexus.tools.registry import ToolRegistry


# =====================================================================
# Helpers
# =====================================================================

def _resolve(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return None


def _detect_format(path: str) -> Optional[str]:
    """Detect file format from extension."""
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".json": "json",
        ".jsonl": "jsonl",
        ".csv": "csv",
        ".tsv": "tsv",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".xml": "xml",
        ".html": "xml",
        ".htm": "xml",
        ".toml": "toml",
        ".ini": "ini",
        ".txt": "text",
    }
    return mapping.get(ext)


# =====================================================================
# Basic YAML parser (no pyyaml dependency)
# =====================================================================

def _parse_yaml_simple(text: str) -> Any:
    """Parse basic YAML without external dependencies.

    Supports:
    - Key-value pairs (key: value)
    - Nested maps via indentation
    - Lists via '- ' prefix
    - Quoted strings
    - Numbers and booleans
    """
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        pass

    # Fallback: basic parser
    lines = text.split("\n")
    if not lines:
        return None

    # Check if it's a simple flat mapping
    simple_pairs = {}
    all_simple = True
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key = key.strip().strip('"').strip("'")
            val = val.strip()
            # Parse value
            simple_pairs[key] = _parse_yaml_value(val)
        elif stripped.startswith("- "):
            all_simple = False
        else:
            all_simple = False

    if all_simple and simple_pairs:
        return simple_pairs

    # More sophisticated parsing with indentation
    try:
        return _parse_yaml_indented(lines)
    except Exception:
        return {"_raw": text, "_note": "Basic YAML parse — complex structures may not be fully supported"}


def _parse_yaml_value(val: str) -> Any:
    """Parse a YAML scalar value."""
    if not val:
        return None
    val = val.strip().strip('"').strip("'")

    # Boolean
    if val.lower() in ("true", "yes", "on"):
        return True
    if val.lower() in ("false", "no", "off"):
        return False

    # None
    if val.lower() in ("null", "~", "none", ""):
        return None

    # Integer
    try:
        return int(val)
    except ValueError:
        pass

    # Float
    try:
        return float(val)
    except ValueError:
        pass

    return val


def _parse_yaml_indented(lines: List[str]) -> Any:
    """Parse YAML with indentation-based nesting."""
    # Determine if it's a list or a map at the top level
    if not lines:
        return {}

    root: Any = {}
    is_list = False
    stack: List[tuple] = []  # (indent_level, key_or_index, container)

    # Check if starts with list items
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            is_list = True
        break

    if is_list:
        root = []
        _parse_yaml_list(lines, root, 0)
    else:
        root = {}
        _parse_yaml_map(lines, root, -1, 0)

    return root if root else None


def _get_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _parse_yaml_map(lines: List[str], target: dict, parent_indent: int, start: int) -> int:
    """Parse YAML map entries starting from *start* line."""
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent <= parent_indent:
            break

        if ":" in stripped and not stripped.startswith("- "):
            key, _, val = stripped.partition(":")
            key = key.strip().strip('"').strip("'")
            val = val.strip()

            if not val:
                # Could be a nested map or list
                i += 1
                if i < len(lines):
                    next_stripped = lines[i].strip()
                    next_indent = _get_indent(lines[i])
                    if next_indent > indent:
                        if next_stripped.startswith("- "):
                            nested: Any = []
                            i = _parse_yaml_list(lines, nested, indent)
                            target[key] = nested
                            continue
                        else:
                            nested = {}
                            i = _parse_yaml_map(lines, nested, indent, i)
                            target[key] = nested
                            continue
                target[key] = None
            else:
                target[key] = _parse_yaml_value(val)
        elif stripped.startswith("- "):
            # List inside map
            nested = []
            i = _parse_yaml_list(lines, nested, indent - 2 if indent >= 2 else 0)
            target[f"_list_{i}"] = nested

        i += 1
    return i


def _parse_yaml_list(lines: List[str], target: list, parent_indent: int) -> int:
    """Parse YAML list entries starting from current position."""
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        indent = _get_indent(line)
        if indent < parent_indent:
            break
        if indent > parent_indent + 2:
            i += 1
            continue

        if stripped.startswith("- "):
            val = stripped[2:].strip()
            if val.endswith(":"):
                # Inline map item
                nested = {}
                i += 1
                if i < len(lines) and _get_indent(lines[i]) > indent:
                    i = _parse_yaml_map(lines, nested, indent, i)
                else:
                    key = val.rstrip(":").strip()
                    nested[key] = None
                target.append(nested)
            else:
                target.append(_parse_yaml_value(val))
        i += 1
    return i


# =====================================================================
# Tool implementations
# =====================================================================

def parse_json(
    path: Optional[str] = None,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse and pretty-print JSON data."""
    if path:
        path = _resolve(path)
        text = _read_text(path)
        if text is None:
            return {"error": f"Could not read file: {path}"}
    elif content:
        text = content
    else:
        return {"error": "Provide either 'path' or 'content'."}

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON: {exc}"}

    pretty = json.dumps(data, indent=2, ensure_ascii=False, default=str)

    # Summary
    summary: Dict[str, Any] = {"type": type(data).__name__}
    if isinstance(data, dict):
        summary["keys"] = list(data.keys())
        summary["count"] = len(data)
    elif isinstance(data, list):
        summary["length"] = len(data)
        if data and isinstance(data[0], dict):
            summary["first_keys"] = list(data[0].keys())

    return {
        "output": pretty,
        "display": pretty,
        "data": {"parsed": data, "summary": summary},
    }


def parse_csv(
    path: str,
    delimiter: str = ",",
    has_header: bool = True,
) -> Dict[str, Any]:
    """Parse a CSV file and return headers and rows."""
    path = _resolve(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
    except Exception as exc:
        return {"error": f"CSV parse error: {exc}"}

    if not rows:
        return {"output": "(empty CSV)", "data": {"headers": [], "rows": [], "row_count": 0}}

    headers = rows[0] if has_header else [f"col_{i}" for i in range(len(rows[0]))]
    data_rows = rows[1:] if has_header else rows

    # Preview (first 20 rows)
    preview_lines = []
    for i, row in enumerate(data_rows[:20]):
        row_dict = dict(zip(headers, row))
        preview_lines.append(f"Row {i + 1}: {json.dumps(row_dict, default=str)}")

    if len(data_rows) > 20:
        preview_lines.append(f"... ({len(data_rows) - 20} more rows)")

    display = "\n".join(preview_lines) if preview_lines else "(no data rows)"

    return {
        "output": f"{len(data_rows)} rows, {len(headers)} columns: {', '.join(headers[:15])}",
        "display": display,
        "data": {
            "headers": headers,
            "rows": data_rows,
            "row_count": len(data_rows),
            "column_count": len(headers),
        },
    }


def parse_yaml(path: str) -> Dict[str, Any]:
    """Parse a YAML file."""
    path = _resolve(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    try:
        data = _parse_yaml_simple(text)
    except Exception as exc:
        return {"error": f"YAML parse error: {exc}"}

    pretty = json.dumps(data, indent=2, ensure_ascii=False, default=str) if data is not None else "(empty)"

    return {
        "output": pretty,
        "display": pretty,
        "data": {"parsed": data},
    }


def parse_xml(path: str) -> Dict[str, Any]:
    """Parse an XML file and return a structured representation."""
    path = _resolve(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return {"error": f"XML parse error: {exc}"}

    def _element_to_dict(el: ET.Element) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "tag": el.tag,
            "attributes": dict(el.attrib) if el.attrib else {},
        }
        children = list(el)
        if children:
            result["children"] = [_element_to_dict(c) for c in children]
        if el.text and el.text.strip():
            result["text"] = el.text.strip()
        return result

    tree_dict = _element_to_dict(root)
    pretty = json.dumps(tree_dict, indent=2, ensure_ascii=False, default=str)

    # Count elements
    all_elements = list(root.iter())
    tags = Counter(el.tag for el in all_elements)

    return {
        "output": f"Root: <{root.tag}>, {len(all_elements)} elements total",
        "display": pretty,
        "data": {
            "root_tag": root.tag,
            "total_elements": len(all_elements),
            "tags": dict(tags),
            "tree": tree_dict,
        },
    }


def convert_format(
    input_path: str,
    output_path: str,
    input_format: Optional[str] = None,
    output_format: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert between data formats (JSON, CSV, XML)."""
    input_path = _resolve(input_path)
    output_path = _resolve(output_path)

    if not os.path.isfile(input_path):
        return {"error": f"Input file not found: {input_path}"}

    in_fmt = (input_format or _detect_format(input_path) or "").lower()
    out_fmt = (output_format or _detect_format(output_path) or "").lower()

    if not in_fmt:
        return {"error": "Could not detect input format. Specify input_format."}
    if not out_fmt:
        return {"error": "Could not detect output format. Specify output_format."}

    text = _read_text(input_path)
    if text is None:
        return {"error": f"Could not read input: {input_path}"}

    # Parse input
    data: Any = None
    headers: List[str] = []
    rows: List[List[str]] = []

    if in_fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return {"error": f"JSON parse error: {exc}"}
    elif in_fmt in ("csv", "tsv"):
        delim = "\t" if in_fmt == "tsv" else ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        rows = list(reader)
        if rows:
            headers = rows[0]
            data_rows = rows[1:]
            # Convert to list of dicts
            data = []
            for row in data_rows:
                row_dict = {}
                for j, h in enumerate(headers):
                    row_dict[h] = row[j] if j < len(row) else ""
                data.append(row_dict)
    elif in_fmt == "xml":
        try:
            root = ET.fromstring(text)
            # Simple conversion: extract all text content
            data = {"tag": root.tag, "text": root.text, "attributes": dict(root.attrib)}
            children = []
            for child in root:
                children.append({"tag": child.tag, "text": child.text, "attributes": dict(child.attrib)})
            data["children"] = children
        except ET.ParseError as exc:
            return {"error": f"XML parse error: {exc}"}
    elif in_fmt == "yaml":
        data = _parse_yaml_simple(text)
    else:
        return {"error": f"Unsupported input format: {in_fmt}"}

    # Write output
    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.isdir(out_dir):
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return {"error": f"Could not create output directory: {exc}"}

    try:
        if out_fmt == "json":
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
        elif out_fmt in ("csv", "tsv"):
            delim = "\t" if out_fmt == "tsv" else ","
            if isinstance(data, list) and data and isinstance(data[0], dict):
                headers = list(data[0].keys())
                with open(output_path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh, delimiter=delim)
                    writer.writerow(headers)
                    for item in data:
                        writer.writerow([str(item.get(h, "")) for h in headers])
            elif isinstance(data, dict):
                headers = list(data.keys())
                with open(output_path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh, delimiter=delim)
                    writer.writerow(headers)
                    writer.writerow([str(data[h]) for h in headers])
            else:
                return {"error": "Cannot convert data to CSV: not a list of objects or a single object."}
        elif out_fmt == "xml":
            if isinstance(data, dict):
                root_tag = data.get("tag", "root")
                elem = ET.Element(root_tag)
                for k, v in data.items():
                    if k in ("tag", "children"):
                        continue
                    if isinstance(v, (str, int, float, bool)):
                        elem.set(k, str(v))
                if isinstance(data.get("children"), list):
                    for child in data["children"]:
                        ce = ET.SubElement(elem, child.get("tag", "item"))
                        for ck, cv in child.get("attributes", {}).items():
                            ce.set(ck, str(cv))
                        if child.get("text"):
                            ce.text = str(child["text"])
                tree = ET.ElementTree(elem)
                ET.indent(tree, space="  ")
                tree.write(output_path, encoding="unicode", xml_declaration=True)
            elif isinstance(data, list) and data:
                root = ET.Element("root")
                for item in data:
                    if isinstance(item, dict):
                        elem = ET.SubElement(root, "item")
                        for k, v in item.items():
                            sub = ET.SubElement(elem, k)
                            sub.text = str(v)
                tree = ET.ElementTree(root)
                ET.indent(tree, space="  ")
                tree.write(output_path, encoding="unicode", xml_declaration=True)
            else:
                return {"error": "Cannot convert data to XML."}
        elif out_fmt == "yaml":
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
                fh.write("\n# Note: written as JSON because pyyaml is not installed\n")
        else:
            return {"error": f"Unsupported output format: {out_fmt}"}
    except Exception as exc:
        return {"error": f"Failed to write output: {exc}"}

    return {
        "output": f"Converted {input_path} ({in_fmt}) → {output_path} ({out_fmt})",
        "data": {"input_format": in_fmt, "output_format": out_fmt,
                 "input_path": input_path, "output_path": output_path},
    }


def analyze_data(
    path: str,
    columns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Basic data analysis on structured data (CSV or JSON)."""
    path = _resolve(path)
    fmt = _detect_format(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    rows_data: List[Dict[str, Any]] = []
    headers: List[str] = []

    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        rows_data = list(reader)
        headers = reader.fieldnames or []
    elif fmt == "json":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                rows_data = data
                if data:
                    headers = list(data[0].keys())
            elif isinstance(data, dict):
                # Single object — analyze its keys
                rows_data = [data]
                headers = list(data.keys())
        except json.JSONDecodeError as exc:
            return {"error": f"JSON parse error: {exc}"}
    else:
        return {"error": f"Unsupported format for analysis: {fmt or 'unknown'}. Use CSV or JSON."}

    if not rows_data:
        return {"output": "(no data to analyze)", "data": {"row_count": 0}}

    total_rows = len(rows_data)

    # Analyze columns
    cols_to_analyze = columns if columns else headers
    stats: Dict[str, Dict[str, Any]] = {}

    for col in cols_to_analyze:
        values = [row.get(col) for row in rows_data if col in row and row.get(col) is not None and str(row.get(col)).strip() != ""]
        if not values:
            stats[col] = {"type": "empty", "count": 0, "missing": total_rows}
            continue

        # Try numeric
        numeric_vals = []
        for v in values:
            try:
                numeric_vals.append(float(v))
            except (ValueError, TypeError):
                break

        if len(numeric_vals) == len(values):
            # Numeric column
            nums = numeric_vals
            nums.sort()
            col_stats: Dict[str, Any] = {
                "type": "numeric",
                "count": len(nums),
                "missing": total_rows - len(values),
                "mean": round(sum(nums) / len(nums), 4) if nums else 0,
                "min": round(min(nums), 4),
                "max": round(max(nums), 4),
                "sum": round(sum(nums), 4),
            }
            n = len(nums)
            if n >= 2:
                median = nums[n // 2] if n % 2 == 1 else (nums[n // 2 - 1] + nums[n // 2]) / 2
                col_stats["median"] = round(median, 4)
                variance = sum((x - col_stats["mean"]) ** 2 for x in nums) / (n - 1)
                col_stats["std_dev"] = round(math.sqrt(variance), 4)
            stats[col] = col_stats
        else:
            # Text column
            str_values = [str(v) for v in values]
            unique = set(str_values)
            value_counts = Counter(str_values)
            most_common = value_counts.most_common(5)

            stats[col] = {
                "type": "text",
                "count": len(str_values),
                "missing": total_rows - len(values),
                "unique": len(unique),
                "top_values": [{"value": v, "count": c} for v, c in most_common],
            }

    # Build display
    lines = [
        f"Data file  : {path}",
        f"Format     : {fmt}",
        f"Rows       : {total_rows}",
        f"Columns    : {len(headers)}",
        f"",
    ]

    for col, s in stats.items():
        lines.append(f"--- {col} ({s['type']}) ---")
        if s["type"] == "numeric":
            lines.append(f"  Count  : {s['count']}  (missing: {s['missing']})")
            lines.append(f"  Mean   : {s['mean']}")
            lines.append(f"  Median : {s.get('median', 'N/A')}")
            lines.append(f"  Std    : {s.get('std_dev', 'N/A')}")
            lines.append(f"  Min    : {s['min']}")
            lines.append(f"  Max    : {s['max']}")
            lines.append(f"  Sum    : {s['sum']}")
        elif s["type"] == "text":
            lines.append(f"  Count  : {s['count']}  (missing: {s['missing']})")
            lines.append(f"  Unique : {s['unique']}")
            if s.get("top_values"):
                lines.append("  Top values:")
                for tv in s["top_values"]:
                    lines.append(f"    {tv['value']}: {tv['count']}")
        lines.append("")

    output = "\n".join(lines)
    return {
        "output": output,
        "display": output,
        "data": {"total_rows": total_rows, "columns": headers, "statistics": stats},
    }


def filter_data(
    path: str,
    column: str,
    operator: str = "eq",
    value: str = "",
) -> Dict[str, Any]:
    """Filter rows in CSV/JSON data by column value."""
    path = _resolve(path)
    fmt = _detect_format(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    valid_ops = ("eq", "ne", "gt", "lt", "gte", "lte", "contains", "starts", "ends")
    if operator not in valid_ops:
        return {"error": f"Invalid operator '{operator}'. Use: {', '.join(valid_ops)}"}

    rows_data: List[Dict[str, Any]] = []
    headers: List[str] = []

    if fmt in ("csv", "tsv"):
        delim = "\t" if fmt == "tsv" else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        rows_data = list(reader)
        headers = reader.fieldnames or []
    elif fmt == "json":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                rows_data = data
                if data:
                    headers = list(data[0].keys())
        except json.JSONDecodeError as exc:
            return {"error": f"JSON parse error: {exc}"}
    else:
        return {"error": f"Unsupported format: {fmt or 'unknown'}. Use CSV or JSON."}

    if column not in headers:
        return {"error": f"Column '{column}' not found. Available: {', '.join(headers[:20])}"}

    # Filter
    matched: List[Dict[str, Any]] = []
    for row in rows_data:
        cell = str(row.get(column, ""))
        val = value

        if operator == "eq" and cell == val:
            matched.append(row)
        elif operator == "ne" and cell != val:
            matched.append(row)
        elif operator == "gt":
            try:
                if float(cell) > float(val):
                    matched.append(row)
            except ValueError:
                pass
        elif operator == "lt":
            try:
                if float(cell) < float(val):
                    matched.append(row)
            except ValueError:
                pass
        elif operator == "gte":
            try:
                if float(cell) >= float(val):
                    matched.append(row)
            except ValueError:
                pass
        elif operator == "lte":
            try:
                if float(cell) <= float(val):
                    matched.append(row)
            except ValueError:
                pass
        elif operator == "contains" and val.lower() in cell.lower():
            matched.append(row)
        elif operator == "starts" and cell.lower().startswith(val.lower()):
            matched.append(row)
        elif operator == "ends" and cell.lower().endswith(val.lower()):
            matched.append(row)

    if not matched:
        return {
            "output": f"No rows matched: {column} {operator} {value}",
            "data": {"matched": 0, "total": len(rows_data), "rows": []},
        }

    # Display
    preview_lines = [f"{len(matched)} row(s) matched: {column} {operator} \"{value}\" (of {len(rows_data)} total)\n"]
    for i, row in enumerate(matched[:30]):
        preview_lines.append(f"Row {i + 1}: {json.dumps(row, default=str)}")
    if len(matched) > 30:
        preview_lines.append(f"... ({len(matched) - 30} more rows)")

    display = "\n".join(preview_lines)

    return {
        "output": f"Matched {len(matched)} of {len(rows_data)} rows",
        "display": display,
        "data": {"matched": len(matched), "total": len(rows_data), "rows": matched},
    }


def json_query(path: str, query: str) -> Dict[str, Any]:
    """Query JSON data using dot-notation path expressions."""
    path = _resolve(path)
    text = _read_text(path)
    if text is None:
        return {"error": f"Could not read file: {path}"}

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"error": f"JSON parse error: {exc}"}

    # Parse dot-notation query
    # Supports: "key", "key.subkey", "key.0", "key.0.subkey"
    parts = query.split(".")
    current: Any = data

    for i, part in enumerate(parts):
        if current is None:
            return {"error": f"Cannot traverse into null at path '{'.'.join(parts[:i])}'"}

        # Array index
        if part.isdigit():
            idx = int(part)
            if isinstance(current, list):
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return {"error": f"Index {idx} out of range (list has {len(current)} items)"}
            elif isinstance(current, dict):
                # Try as string key
                current = current.get(part)
            else:
                return {"error": f"Cannot index into {type(current).__name__} at '{part}'"}
        else:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None and part not in current if isinstance(data, dict) else True:
                    # Check key exists
                    if isinstance(data, dict) and part not in data:
                        # Partial traversal — may be fine
                        pass
            elif isinstance(current, list):
                # Try to match all items
                try:
                    results = []
                    for item in current:
                        if isinstance(item, dict):
                            val = item.get(part)
                            if val is not None:
                                results.append(val)
                    current = results
                except Exception:
                    return {"error": f"Cannot access '{part}' on list at path '{'.'.join(parts[:i])}'"}
            else:
                return {"error": f"Cannot access '{part}' on {type(current).__name__}"}

    pretty = json.dumps(current, indent=2, ensure_ascii=False, default=str) if current is not None else "null"

    return {
        "output": pretty,
        "display": pretty,
        "data": {"query": query, "result": current},
    }


# =====================================================================
# Registration
# =====================================================================

_DATA_TOOLS = [
    (
        "parse_json",
        "Parse and pretty-print JSON data from a file or inline content.",
        [
            ToolParameter("path", "string", "Path to JSON file", required=False, default=None),
            ToolParameter("content", "string", "Inline JSON content", required=False, default=None),
        ],
        parse_json,
        False,
    ),
    (
        "parse_csv",
        "Parse a CSV file and return headers and rows.",
        [
            ToolParameter("path", "string", "Path to CSV file"),
            ToolParameter("delimiter", "string", "Column delimiter", required=False, default=","),
            ToolParameter("has_header", "boolean", "First row is header", required=False, default=True),
        ],
        parse_csv,
        False,
    ),
    (
        "parse_yaml",
        "Parse a YAML file. Uses pyyaml if available, otherwise a basic built-in parser.",
        [
            ToolParameter("path", "string", "Path to YAML file"),
        ],
        parse_yaml,
        False,
    ),
    (
        "parse_xml",
        "Parse an XML file and return a structured tree representation.",
        [
            ToolParameter("path", "string", "Path to XML file"),
        ],
        parse_xml,
        False,
    ),
    (
        "convert_format",
        "Convert data between formats (JSON, CSV, TSV, XML).",
        [
            ToolParameter("input_path", "string", "Input file path"),
            ToolParameter("output_path", "string", "Output file path"),
            ToolParameter("input_format", "string", "Input format (auto-detected from extension)", required=False, default=None),
            ToolParameter("output_format", "string", "Output format (auto-detected from extension)", required=False, default=None),
        ],
        convert_format,
        False,
    ),
    (
        "analyze_data",
        "Perform basic data analysis on structured data (CSV or JSON): "
        "count, mean, min, max for numbers; unique values for text.",
        [
            ToolParameter("path", "string", "Path to CSV or JSON file"),
            ToolParameter("columns", "array", "Specific columns to analyze (default: all)", required=False, default=None),
        ],
        analyze_data,
        False,
    ),
    (
        "filter_data",
        "Filter rows in CSV/JSON data by column value with comparison operators.",
        [
            ToolParameter("path", "string", "Path to CSV or JSON file"),
            ToolParameter("column", "string", "Column name to filter on"),
            ToolParameter("operator", "string", "Comparison operator", required=False, default="eq",
                          enum=["eq", "ne", "gt", "lt", "gte", "lte", "contains", "starts", "ends"]),
            ToolParameter("value", "string", "Value to compare against", default=""),
        ],
        filter_data,
        False,
    ),
    (
        "json_query",
        "Query JSON data using dot-notation path expressions (e.g. 'users.0.name').",
        [
            ToolParameter("path", "string", "Path to JSON file"),
            ToolParameter("query", "string", "Dot-notation path (e.g. 'users.0.name')"),
        ],
        json_query,
        False,
    ),
]


def register_all(reg: ToolRegistry) -> None:
    """Register all data tools with the given registry."""
    for name, desc, params, func, dangerous in _DATA_TOOLS:
        reg.register_function(name=name, description=desc, parameters=params,
                              func=func, dangerous=dangerous)
