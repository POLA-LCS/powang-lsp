"""Language Server Protocol implementation for powang.

The server is shipped with the powang-lsp extension. It imports the language
implementation from the powang repository, which is selected with the
POWANG_REPO environment variable or the current working directory.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(os.environ.get("POWANG_REPO", "")).resolve() if os.environ.get("POWANG_REPO") else None
if ROOT is None or not (ROOT / "src" / "parser.py").exists():
    # Fall back to the extension's own bundled src/.
    bundled = Path(__file__).resolve().parents[1] / "src"
    if bundled.exists():
        ROOT = bundled.parent
    else:
        ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser import Parser  # noqa: E402
from src.typecheck import check_source  # noqa: E402

KEYWORDS = [
    "if", "else", "for", "fun", "return", "use", "type", "extern",
    "try", "catch", "finally", "spawn", "export", "match", "case", "const", "as",
    "enum",
]

BUILTINS = [
    "print", "println", "format", "printf", "error", "fail", "input", "inputf", "typeof", "size",
    "open", "write", "read", "close", "system", "wait", "cancel", "task_status",
]

BUILTIN_TYPES = {
    "any", "int", "num", "bool", "str", "arr", "map", "tup",
    "function", "file", "task",
}

SEMANTIC_TOKEN_TYPES = [
    "namespace",
    "type",
    "parameter",
    "variable",
    "property",
    "function",
    "method",
    "macro",
    "keyword",
    "comment",
    "string",
    "number",
    "operator",
    "builtin",
    "builtinType",
    "constant",
]
SEMANTIC_TYPE_INDEX = {name: index for index, name in enumerate(SEMANTIC_TOKEN_TYPES)}

BUILTIN_DOCS: dict[str, tuple[str, str]] = {
    "print": ("print(...) -> int", "Writes each argument without adding a newline. Returns the argument count."),
    "println": ("println(...) -> int", "Writes each argument and then a newline."),
    "format": ("format(template, ...) -> str", "Returns a formatted string with {0}, {1} and {n/separator} placeholders."),
    "printf": ("printf(template, ...) -> int", "Formats a string and prints it in one call."),
    "error": ("error(message, ...) -> error", "Raises a catchable error."),
    "fail": ("fail(kind, message, ...) -> error", "Creates an error value for error-union returns."),
    "system": ("system(command, ...) -> int", "Runs a system command."),
    "input": ("input(receptor?) -> receptor", "Reads one line of input into the receptor."),
    "inputf": ("inputf(receptor, prompt) -> receptor", "Prints the prompt and then reads one line into the receptor."),
    "typeof": ("typeof(value) -> str", "Returns the runtime type name of a value."),
    "size": ("size(...) -> int", "Returns the total size of the given iterables."),
    "open": ("open(path, mode?) -> file", "Opens a file."),
    "write": ("write(file, text) -> any", "Writes text to a file."),
    "read": ("read(file) -> str", "Reads a file."),
    "close": ("close(file) -> bool", "Closes a file."),
    "wait": ("wait(task, timeout_ms?) -> any", "Waits for a task and returns its result."),
    "cancel": ("cancel(task) -> any", "Cancels a task."),
    "task_status": ("task_status(task) -> str", "Returns the status of a task."),
}

BUILTIN_TYPE_DOCS: dict[str, str] = {
    "any": "The gradual unknown type. It accepts any value.",
    "int": "A whole number.",
    "num": "A floating-point number.",
    "bool": "Either true or false.",
    "str": "A sequence of characters.",
    "arr": "dynamic-sized collection | arr[type]",
    "tup": "fixed-size collection | tup[type, type, ...]",
    "map": "A key-value collection.",
    "function": "A callable value.",
    "file": "An open file stream.",
    "task": "A handle to a spawned task.",
    "error": "A structured error value.",
}

KEYWORD_DOCS: dict[str, str] = {
    "if": "Runs a block when the condition is truthy.",
    "else": "Runs the alternative branch of an if statement.",
    "for": "Repeats a block. Supports ranges and for-each loops.",
    "fun": "Declares a function.",
    "return": "Returns a value from the current function.",
    "use": "Imports a module.",
    "type": "Declares a user type or a type alias.",
    "extern": "Declares an external function or type.",
    "try": "Starts a try block.",
    "catch": "Catches an error from a try block.",
    "finally": "Runs a block after try and catch.",
    "spawn": "Starts a task.",
    "export": "Exports a declaration from a module.",
    "match": "Matches a value against a list of cases.",
    "case": "Declares one match case.",
    "const": "Declares a compile-time macro.",
    "as": "Casts a value to a type or introduces a module alias.",
    "this": "The current instance inside a method.",
}

CONSTANT_DOCS: dict[str, str] = {
    "true": "The bool true value.",
    "false": "The bool false value.",
    "nova": "The absence of a value. It is falsey in conditions.",
}

DOCUMENTS: dict[str, str] = {}
WORKSPACE_ROOT: str | None = None


def send(message: dict) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n")
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n", b""):
            break
        key, _, value = line.decode("ascii", errors="replace").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _line_number(error: Exception) -> int:
    line = getattr(error, "line", None)
    if isinstance(line, int) and line > 0:
        return line - 1
    if isinstance(line, str) and line.isdigit():
        return int(line) - 1
    return 0


def _source_path(uri: str) -> str | None:
    if not uri.startswith("file://"):
        return None
    path = unquote(urlsplit(uri).path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path


def _diag(uri: str, line: int, col: int, end_col: int, severity: int, code: str, message: str, tags: list[int] | None = None, source: str = "powang") -> dict:
    item = {
        "range": {
            "start": {"line": line, "character": col},
            "end": {"line": line, "character": max(col + 1, end_col)},
        },
        "severity": severity,
        "source": source,
        "code": code,
        "message": message,
    }
    if tags:
        item["tags"] = tags
    return item


def _is_comment_line(lines: list[str], index: int) -> bool:
    # Determine if a line is inside or is a comment.
    in_block = False
    for i in range(0, index + 1):
        s = lines[i].strip()
        if in_block:
            if "!#" in s:
                in_block = False
            continue
        if s.startswith("#!"):
            if "!#" in s and s.index("!#") > s.index("#!"):
                continue
            in_block = True
            if i == index:
                return True
            continue
        if s.startswith("##"):
            if i == index:
                return True
    return in_block


def _lint_document(text: str, uri: str) -> list[dict]:
    diagnostics: list[dict] = []
    lines = _lines(text)
    path = _source_path(uri)

    # Trailing whitespace and line length and final newline.
    for index, line in enumerate(lines):
        if _is_comment_line(lines, index):
            continue
        if line != line.rstrip(" \t"):
            diagnostics.append(_diag(uri, index, len(line.rstrip(" \t")), len(line), 2, "PW004", "trailing whitespace", [1]))
    if text and not text.endswith("\n"):
        diagnostics.append(_diag(uri, len(lines) - 1, 0, 1, 3, "PW005", "missing final newline"))

    # Unused imports tracking.
    imported_names: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if _is_comment_line(lines, index):
            continue
        stripped = line.strip()
        use_match = re.match(r"^use\s+(?:\"[^\"]+\"|([A-Za-z_][A-Za-z0-9_]*))(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*|\*))?", stripped)
        if use_match:
            name = use_match.group(2) or use_match.group(1)
            if name and name != "*":
                imported_names.append((index, name))

    # Count identifier occurrences excluding the import line itself.
    full_text = text
    for import_line, name in imported_names:
        # count occurrences of name as whole word, excluding its own import line
        occurrences = 0
        for li, line in enumerate(lines):
            if li == import_line:
                continue
            for match in re.finditer(r"\b" + re.escape(name) + r"\b", line):
                occurrences += 1
        if occurrences == 0:
            diagnostics.append(_diag(uri, import_line, 0, len(lines[import_line]), 2, "PW001", f"unused import '{name}'", [1]))

    # Unused variables: simple top-level and local heuristic via declared names.
    # Track declared variable/const names and check references.
    declared: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if _is_comment_line(lines, index):
            continue
        stripped = line.strip()
        const_match = re.match(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if const_match:
            declared.append((index, const_match.group(1)))
            continue
        var_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?\s*(?::=|=)", stripped)
        if var_match and var_match.group(1) not in KEYWORDS:
            declared.append((index, var_match.group(1)))

    for decl_line, name in declared:
        occurrences = 0
        for li, line in enumerate(lines):
            if li == decl_line:
                continue
            for match in re.finditer(r"\b" + re.escape(name) + r"\b", line):
                occurrences += 1
        if occurrences == 0:
            diagnostics.append(_diag(uri, decl_line, 0, len(lines[decl_line]), 2, "PW002", f"unused variable '{name}'", [1]))

    # Naming convention: functions and variables should be snake_case.
    in_block_comment = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if in_block_comment:
            if "!#" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("#!"):
            in_block_comment = True
            if "!#" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("##"):
            continue
        fun_match = re.search(r"\bfun\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if fun_match:
            name = fun_match.group(1)
            if name != name.lower() or "-" in name:
                if not name.islower() or any(c.isupper() for c in name):
                    diagnostics.append(_diag(uri, index, fun_match.start(1), fun_match.end(1), 3, "PW006", f"function name '{name}' should be snake_case", None))
        const_match = re.search(r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if const_match:
            name = const_match.group(1)
            if any(c.islower() for c in name) and name != name.upper() and "_" in name:
                pass
            # constants should be UPPER_SNAKE_CASE
            if name != name.upper():
                diagnostics.append(_diag(uri, index, const_match.start(1), const_match.end(1), 3, "PW006", f"constant name '{name}' should be UPPER_SNAKE_CASE", None))

    # Complexity: function body length and nesting depth.
    # Simple heuristic: count lines between a fun declaration and its closing brace.
    i = 0
    while i < len(lines):
        if _is_comment_line(lines, i):
            i += 1
            continue
        if re.search(r"\bfun\s+[A-Za-z_]", lines[i]):
            start = i
            depth = 0
            started = False
            j = i
            while j < len(lines):
                for ch in lines[j]:
                    if ch == "{":
                        depth += 1
                        started = True
                    elif ch == "}":
                        depth -= 1
                if started and depth == 0:
                    break
                j += 1
            body_lines = j - start
            if body_lines > 50:
                diagnostics.append(_diag(uri, start, 0, len(lines[start]), 3, "PW008", f"function body too long ({body_lines} lines)", None))
            # nesting depth
            max_depth = 0
            cur = 0
            for k in range(start, min(j + 1, len(lines))):
                for ch in lines[k]:
                    if ch == "{":
                        cur += 1
                        if cur > max_depth:
                            max_depth = cur
                    elif ch == "}":
                        cur -= 1
            if max_depth > 5:
                diagnostics.append(_diag(uri, start, 0, len(lines[start]), 3, "PW008", f"nesting too deep ({max_depth})", None))
            i = j + 1
            continue
        i += 1

    # Import order: use statements should be grouped and sorted.
    use_lines = [(idx, lines[idx].strip()) for idx, line in enumerate(lines) if line.strip().startswith("use ") and not _is_comment_line(lines, idx)]
    if len(use_lines) > 1:
        names = [l.strip() for _, l in use_lines]
        if names != sorted(names):
            diagnostics.append(_diag(uri, use_lines[0][0], 0, len(lines[use_lines[0][0]]), 3, "PW007", "imports are not sorted", None))

    # Duplicate imports
    seen_imports: set[str] = set()
    for idx, line in enumerate(lines):
        if _is_comment_line(lines, idx):
            continue
        stripped = line.strip()
        if stripped.startswith("use "):
            if stripped in seen_imports:
                diagnostics.append(_diag(uri, idx, 0, len(line), 2, "PW009", "duplicate import", [1]))
            seen_imports.add(stripped)

    return diagnostics


def diagnose(uri: str, text: str) -> None:
    diagnostics: list[dict] = []
    source_path = _source_path(uri)
    try:
        parser = Parser(text, source_path=source_path)
        parser.parse()
    except Exception as error:
        # Try to extract line info
        line_no = _line_number(error)
        diagnostics.append(_diag(uri, line_no, 0, 1, 1, "PW100", str(error)))
    else:
        try:
            for type_error in check_source(text, source_path):
                line_no = _line_number(type_error)
                diagnostics.append(_diag(uri, line_no, 0, 1, 1, "PW101", str(type_error)))
        except Exception as error:  # noqa: BLE001
            diagnostics.append(_diag(uri, 0, 0, 1, 2, "PW102", f"internal checker error: {error}"))

    diagnostics.extend(_lint_document(text, uri))

    send({
        "jsonrpc": "2.0",
        "method": "textDocument/publishDiagnostics",
        "params": {
            "uri": uri,
            "diagnostics": diagnostics,
        },
    })


def _lines(text: str) -> list[str]:
    return text.split("\n")


def _strip_semicolon(value: str) -> str:
    return value.strip().rstrip(";").strip()


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    escape = False
    for char in text:
        if in_string:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def _parse_parameters(params_text: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for part in _split_top_level(params_text, ","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, rest = part.split(":", 1)
            name = name.strip()
            type_text = rest.split("=", 1)[0].strip()
        else:
            name = part.split("=", 1)[0].strip()
            type_text = "any"
        if name:
            result.append((name, type_text))
    return result


def _parse_function_signature(line: str) -> dict | None:
    fun_match = re.search(r"\bfun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
    if not fun_match:
        return None
    name = fun_match.group(1)
    name_col = fun_match.start(1)
    name_end_col = fun_match.end(1)
    open_index = line.rfind("(", 0, fun_match.end(0))
    if open_index < 0:
        return None
    depth = 0
    close_index = -1
    in_string = False
    escape = False
    for index in range(open_index, len(line)):
        char = line[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index < 0:
        return None
    params_text = line[open_index + 1:close_index]
    after = line[close_index + 1:]
    return_type = "nova"
    return_match = re.match(r"\s*:\s*([^\s{>]+)", after)
    if return_match:
        return_type = return_match.group(1).strip()
    signature = line.strip()
    if ">>" in signature:
        signature = signature.split(">>", 1)[0].strip()
    if "{" in signature:
        signature = signature.split("{", 1)[0].strip()
    signature = signature.rstrip(";").strip().lstrip("+- ").strip()
    return {
        "name": name,
        "name_col": name_col,
        "name_end_col": name_end_col,
        "parameters": _parse_parameters(params_text),
        "return_type": return_type,
        "signature": signature,
    }


def _infer_expression_type(expr: str, by_name: dict[str, list[dict]]) -> str:
    expr = _strip_semicolon(expr)
    if not expr:
        return "any"
    cast_match = re.search(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])?)\s*$", expr)
    if cast_match:
        return cast_match.group(1)
    if expr.startswith('$"') or expr.startswith('"'):
        return "str"
    if expr in {"true", "false"}:
        return "bool"
    if expr == "nova":
        return "nova"
    if re.fullmatch(r"-?\d+", expr):
        return "int"
    if re.fullmatch(r"-?\d+\.\d+(?:[eE][+-]?\d+)?", expr):
        return "num"
    if expr.startswith("["):
        if ">>" in expr:
            return "map"
        inner = expr[1:-1].strip()
        if not inner:
            return "arr"
        elements = _split_top_level(inner, ",")
        if len(elements) == 1:
            elements = _split_top_level(inner, " ")
        types = [_infer_expression_type(element, by_name) for element in elements if element.strip()]
        if types and all(element_type == types[0] for element_type in types):
            return f"arr[{types[0]}]"
        return "arr"
    call_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", expr)
    if call_match:
        for symbol in by_name.get(call_match.group(1), []):
            if symbol["kind"] in {"function", "method"} and symbol.get("type"):
                return symbol["type"]
        return "any"
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expr):
        for symbol in by_name.get(expr, []):
            if symbol["kind"] in {"variable", "parameter", "const"}:
                return symbol["type"]
    return "any"


def _collect_doc_comment(lines: list[str], index: int) -> str:
    parts: list[str] = []
    cursor = index - 1
    while cursor >= 0:
        stripped = lines[cursor].strip()
        if stripped.startswith("##"):
            parts.append(stripped[2:].strip())
            cursor -= 1
            continue
        if stripped.endswith("!#"):
            block: list[str] = []
            while cursor >= 0:
                block.append(lines[cursor].strip())
                if lines[cursor].strip().startswith("#!"):
                    break
                cursor -= 1
            text = "\n".join(reversed(block))
            text = text.replace("#!", "", 1)
            if text.endswith("!#"):
                text = text[:-2]
            parts.append(text.strip())
            cursor -= 1
            continue
        break
    return "\n".join(reversed(parts)).strip()


def build_document_index(text: str, path: str | None = None) -> dict:
    lines = _lines(text)
    symbols: list[dict] = []
    by_name: dict[str, list[dict]] = {}
    modules: dict[str, str | None] = {}
    properties: dict[tuple[str, str], dict] = {}
    current_type: str | None = None
    line_index = 0

    def add_symbol(symbol: dict, documentation: str = "") -> None:
        symbol["documentation"] = documentation
        symbols.append(symbol)
        by_name.setdefault(symbol["name"], []).append(symbol)
        if symbol.get("container"):
            properties[(symbol["container"], symbol["name"])] = symbol

    while line_index < len(lines):
        line = lines[line_index]
        stripped = line.strip()
        if not stripped:
            line_index += 1
            continue
        if stripped.startswith("##"):
            line_index += 1
            continue
        if stripped.startswith("#!"):
            while line_index < len(lines) and "!#" not in lines[line_index]:
                line_index += 1
            line_index += 1
            continue

        doc = _collect_doc_comment(lines, line_index)

        type_match = re.match(r"^\s*(?:export\s+)?type\s+([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", line)
        if type_match:
            name = type_match.group(1)
            rest = type_match.group(2).strip()
            type_name = name
            if rest.startswith(">>"):
                type_name = _strip_semicolon(rest[2:])
            add_symbol({
                "name": name,
                "kind": "type",
                "line": line_index,
                "col": type_match.start(1),
                "end_col": type_match.end(1),
                "type": type_name,
                "signature": stripped,
                "decl_text": stripped,
            }, doc)
            if "{" in rest:
                current_type = name
            line_index += 1
            continue

        if current_type and stripped.startswith("}"):
            current_type = None
            line_index += 1
            continue

        if current_type:
            if re.match(r"^\s*[+-]\s*fun\s+", line):
                parsed = _parse_function_signature(line)
                if parsed:
                    add_symbol({
                        "name": parsed["name"],
                        "kind": "method",
                        "line": line_index,
                        "col": parsed["name_col"],
                        "end_col": parsed["name_end_col"],
                        "type": parsed["return_type"],
                        "signature": parsed["signature"],
                        "container": current_type,
                    }, doc)
                    for parameter_name, parameter_type in parsed["parameters"]:
                        add_symbol({
                            "name": parameter_name,
                            "kind": "parameter",
                            "line": line_index,
                            "col": parsed["name_col"],
                            "end_col": parsed["name_end_col"],
                            "type": parameter_type,
                            "container": parsed["name"],
                        })
                line_index += 1
                continue
            property_match = re.match(r"^\s*[+-]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^;]+?)\s*;?\s*$", line)
            if property_match:
                add_symbol({
                    "name": property_match.group(1),
                    "kind": "property",
                    "line": line_index,
                    "col": property_match.start(1),
                    "end_col": property_match.end(1),
                    "type": _strip_semicolon(property_match.group(2)),
                    "container": current_type,
                }, doc)
                line_index += 1
                continue

        if re.match(r"^\s*(?:export\s+)?(?:extern\s+)?fun\b", line):
            parsed = _parse_function_signature(line)
            if parsed:
                add_symbol({
                    "name": parsed["name"],
                    "kind": "function",
                    "line": line_index,
                    "col": parsed["name_col"],
                    "end_col": parsed["name_end_col"],
                    "type": parsed["return_type"],
                    "signature": parsed["signature"],
                }, doc)
                for parameter_name, parameter_type in parsed["parameters"]:
                    add_symbol({
                        "name": parameter_name,
                        "kind": "parameter",
                        "line": line_index,
                        "col": parsed["name_col"],
                        "end_col": parsed["name_end_col"],
                        "type": parameter_type,
                        "container": parsed["name"],
                    })
            line_index += 1
            continue

        const_match = re.match(r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([^=]+?))?\s*=\s*(.+?)\s*;?\s*$", line)
        if const_match:
            name = const_match.group(1)
            type_text = _strip_semicolon(const_match.group(2) or "")
            value = _strip_semicolon(const_match.group(3))
            if not type_text:
                type_text = _infer_expression_type(value, by_name)
            add_symbol({
                "name": name,
                "kind": "const",
                "line": line_index,
                "col": const_match.start(1),
                "end_col": const_match.end(1),
                "type": type_text,
                "value": value,
                "decl_text": stripped,
            }, doc)
            line_index += 1
            continue

        use_match = re.match(r"^\s*use\s+(?:\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*|\*))?", line)
        if use_match:
            path_spec = use_match.group(1)
            module_name = use_match.group(2)
            alias = use_match.group(3) or module_name or (Path(path_spec).stem if path_spec else "")
            if alias != "*":
                start = use_match.start(1) if use_match.start(1) >= 0 else use_match.start(2)
                end = use_match.end(1) if use_match.end(1) >= 0 else use_match.end(2)
                add_symbol({
                    "name": alias,
                    "kind": "module",
                    "line": line_index,
                    "col": start,
                    "end_col": end,
                    "type": "module",
                    "path": path_spec,
                    "module": module_name,
                    "decl_text": stripped,
                }, doc)
                modules[alias] = path_spec
            line_index += 1
            continue

        var_match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*([^=;]+?))?\s*(?::=|=)\s*(.+?)\s*;?\s*$", line)
        if var_match:
            name = var_match.group(1)
            if name not in KEYWORDS:
                type_text = _strip_semicolon(var_match.group(2) or "")
                value = _strip_semicolon(var_match.group(3))
                annotated = bool(type_text)
                if not type_text:
                    type_text = _infer_expression_type(value, by_name)
                add_symbol({
                    "name": name,
                    "kind": "variable",
                    "line": line_index,
                    "col": var_match.start(1),
                    "end_col": var_match.end(1),
                    "type": type_text,
                    "value": value,
                    "annotated": annotated,
                    "decl_text": stripped,
                }, doc)
                line_index += 1
                continue

        var_decl_match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^=;]+?)\s*;?\s*$", line)
        if var_decl_match:
            name = var_decl_match.group(1)
            if name not in KEYWORDS:
                add_symbol({
                    "name": name,
                    "kind": "variable",
                    "line": line_index,
                    "col": var_decl_match.start(1),
                    "end_col": var_decl_match.end(1),
                    "type": _strip_semicolon(var_decl_match.group(2)),
                    "annotated": True,
                    "decl_text": stripped,
                }, doc)
                line_index += 1
                continue

        line_index += 1

    return {
        "symbols": symbols,
        "by_name": by_name,
        "modules": modules,
        "properties": properties,
        "lines": lines,
        "path": path,
    }


def _symbol_markdown(symbol: dict) -> str:
    kind = symbol["kind"]
    name = symbol["name"]
    documentation = symbol.get("documentation", "").strip()
    if kind == "function":
        body = f"**function** `{symbol.get('signature', name)}`"
    elif kind == "method":
        body = f"**method** `{symbol.get('signature', name)}`"
    elif kind == "type":
        if symbol.get("type") and symbol.get("type") != name:
            body = f"**type** `{name} = {symbol['type']}`"
        else:
            body = f"**type** `{name}`"
    elif kind == "const":
        body = f"**const** `{symbol.get('decl_text', name)}`"
    elif kind == "module":
        body = f"**module** `{symbol.get('decl_text', name)}`"
    elif kind == "parameter":
        body = f"**parameter** `{name}: {symbol.get('type', 'any')}`"
    elif kind == "property":
        body = f"**property** `{name}: {symbol.get('type', 'any')}`"
    else:
        body = f"**variable** `{name}: {symbol.get('type', 'any')}`"
    if documentation:
        body += f"\n\n{documentation}"
    return body


def _symbol_hover_result(symbol: dict, line: int, start: int, end: int) -> dict:
    return {
        "contents": {"kind": "markdown", "value": _symbol_markdown(symbol)},
        "range": {
            "start": {"line": line, "character": start},
            "end": {"line": line, "character": end},
        },
    }


def _word_position(text: str, line: int, character: int) -> tuple[str, int, int]:
    lines = _lines(text)
    if line < 0 or line >= len(lines):
        return "", 0, 0
    current = lines[line]
    character = max(0, min(character, len(current)))
    start = character
    while start > 0 and (current[start - 1].isalnum() or current[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(current) and (current[end].isalnum() or current[end] == "_"):
        end += 1
    return current[start:end], start, end


def _object_name_before_dot(line: str, dot_index: int) -> str:
    index = dot_index - 1
    while index >= 0 and line[index].isspace():
        index -= 1
    end = index + 1
    while index >= 0 and (line[index].isalnum() or line[index] == "_"):
        index -= 1
    return line[index + 1:end]


def _module_index_for(module_symbol: dict, current_path: str | None) -> dict | None:
    path_spec = module_symbol.get("path")
    module_name = module_symbol.get("module")
    candidate: Path | None = None
    if path_spec:
        candidate = Path(path_spec)
        if not candidate.is_absolute() and current_path:
            candidate = Path(current_path).parent / candidate
    elif module_name:
        candidate = ROOT / "modules" / module_name / "use.po"
    if candidate is None or not candidate.exists():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    index = build_document_index(text, str(candidate))
    index["uri"] = candidate.resolve().as_uri()
    return index


def _resolve_symbol(text: str, word: str, line: int, character: int, path: str | None) -> tuple[dict | None, dict]:
    index = build_document_index(text, path)
    lines = _lines(text)
    current = lines[line] if 0 <= line < len(lines) else ""
    before = current[:character]
    stripped_before = before.rstrip()
    if stripped_before.endswith("."):
        dot_index = len(stripped_before) - 1
        object_name = _object_name_before_dot(current, dot_index)
        object_symbols = index["by_name"].get(object_name, [])
        object_symbol = object_symbols[0] if object_symbols else None
        if object_symbol and object_symbol["kind"] == "module":
            module_index = _module_index_for(object_symbol, path)
            if module_index:
                members = module_index["by_name"].get(word, [])
                if members:
                    return members[0], module_index
        elif object_symbol:
            property_symbol = index["properties"].get((object_symbol.get("type", ""), word))
            if property_symbol:
                return property_symbol, index
        return None, index
    symbols = index["by_name"].get(word, [])
    if symbols:
        return symbols[0], index
    return None, index


def handle_initialize(request_id, params) -> None:
    global WORKSPACE_ROOT
    root_uri = params.get("rootUri")
    if not root_uri:
        folders = params.get("workspaceFolders") or []
        if folders:
            root_uri = folders[0].get("uri")
    if root_uri:
        WORKSPACE_ROOT = _source_path(root_uri)
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "capabilities": {
                "textDocumentSync": 1,
                "completionProvider": {
                    "triggerCharacters": [".", ":", "@", "&"],
                },
                "hoverProvider": True,
                "signatureHelpProvider": {
                    "triggerCharacters": ["(", ","],
                },
                "definitionProvider": True,
                "declarationProvider": True,
                "typeDefinitionProvider": True,
                "documentHighlightProvider": True,
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "referencesProvider": True,
                "renameProvider": {
                    "prepareProvider": True,
                },
                "documentFormattingProvider": True,
                "documentRangeFormattingProvider": True,
                "codeActionProvider": {
                    "codeActionKinds": ["quickfix", "source", "source.fixAll", "source.organizeImports"],
                },
                "executeCommandProvider": {
                    "commands": ["powang.formatDocument", "powang.organizeImports"],
                },
                "inlayHintProvider": True,
                "foldingRangeProvider": True,
                "semanticTokensProvider": {
                    "legend": {
                        "tokenTypes": SEMANTIC_TOKEN_TYPES,
                        "tokenModifiers": [],
                    },
                    "full": True,
                },
            },
            "serverInfo": {
                "name": "powang-lsp",
                "version": "0.9.2",
            },
        },
    })


def _completion_kind(kind: str) -> int:
    return {
        "function": 3,
        "method": 2,
        "type": 7,
        "const": 21,
        "variable": 6,
        "parameter": 6,
        "module": 9,
        "property": 10,
    }.get(kind, 6)


def handle_completion(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    path = _source_path(uri)
    index = build_document_index(text, path)
    lines = _lines(text)
    current = lines[line] if 0 <= line < len(lines) else ""
    before = current[:character]
    stripped_before = before.rstrip()
    items: list[dict] = []
    seen: set[str] = set()

    def add(label: str, kind: int, detail: str = "", documentation: str = "",
            insert_text: str | None = None, sort_text: str | None = None,
            insert_text_format: int | None = None) -> None:
        if label in seen:
            return
        seen.add(label)
        item: dict = {"label": label, "kind": kind}
        if detail:
            item["detail"] = detail
        if documentation:
            item["documentation"] = {"kind": "markdown", "value": documentation}
        if insert_text is not None:
            item["insertText"] = insert_text
        if insert_text_format is not None:
            item["insertTextFormat"] = insert_text_format
        if sort_text is not None:
            item["sortText"] = sort_text
        items.append(item)

    if stripped_before.endswith("."):
        dot_index = len(stripped_before) - 1
        object_name = _object_name_before_dot(current, dot_index)
        object_symbols = index["by_name"].get(object_name, [])
        object_symbol = object_symbols[0] if object_symbols else None
        if object_symbol and object_symbol["kind"] == "module":
            module_index = _module_index_for(object_symbol, path)
            if module_index:
                for symbol in module_index["symbols"]:
                    if symbol["kind"] in {"function", "type", "const", "module"}:
                        add(
                            symbol["name"],
                            _completion_kind(symbol["kind"]),
                            symbol.get("signature", symbol.get("type", "")),
                            _symbol_markdown(symbol),
                            sort_text="0",
                        )
        elif object_symbol:
            object_type = object_symbol.get("type", "")
            for (container, prop_name), symbol in index["properties"].items():
                if container == object_type:
                    add(
                        prop_name,
                        _completion_kind(symbol["kind"]),
                        symbol.get("type", ""),
                        _symbol_markdown(symbol),
                        sort_text="0",
                    )
        send({"jsonrpc": "2.0", "id": request_id, "result": items})
        return

    stripped_line = before.strip()
    type_context = (
        stripped_line.endswith(":")
        or stripped_line.endswith("@")
        or stripped_line.endswith("&")
        or re.search(r"arr\[\s*$", stripped_line) is not None
    )
    if type_context:
        for name, documentation in BUILTIN_TYPE_DOCS.items():
            add(name, 7, "builtin type", f"**builtin type** `{name}`\n\n{documentation}", sort_text="1")
        for symbol in index["symbols"]:
            if symbol["kind"] == "type":
                add(symbol["name"], 7, symbol.get("type", "type"), _symbol_markdown(symbol), sort_text="0")
        send({"jsonrpc": "2.0", "id": request_id, "result": items})
        return

    for symbol in index["symbols"]:
        if symbol["kind"] in {"property", "parameter"} or symbol.get("container"):
            continue
        add(
            symbol["name"],
            _completion_kind(symbol["kind"]),
            symbol.get("signature", symbol.get("type", "")),
            _symbol_markdown(symbol),
            sort_text="0",
        )
    for name, documentation in BUILTIN_TYPE_DOCS.items():
        add(name, 7, "builtin type", f"**builtin type** `{name}`\n\n{documentation}", sort_text="2")
    for name, (signature, documentation) in BUILTIN_DOCS.items():
        add(
            name,
            3,
            signature,
            f"**builtin function** `{signature}`\n\n{documentation}",
            insert_text=f"{name}($1)",
            sort_text="3",
            insert_text_format=2,
        )
    for name in KEYWORDS:
        add(name, 14, "keyword", f"**keyword** `{name}`\n\n{KEYWORD_DOCS.get(name, '')}", sort_text="4")
    for label, snippet, detail in (
        ("fun", "fun ${1:name}(${2})${3: : ${4:type}} {\n\t$0\n}", "function declaration"),
        ("type", "type ${1:Name} {\n\t$0\n}", "type declaration"),
        ("match", "match ${1:value} {\n\tcase ${2:_} >> $0;\n}", "match statement"),
        ("for", "for ${1:item} >> ${2:items} {\n\t$0\n}", "for-each loop"),
        ("if", "if ${1:condition} {\n\t$0\n}", "if statement"),
        ("try", "try {\n\t$0\n} catch ${1:error} {\n\t\n}", "try statement"),
    ):
        items.append({
            "label": label,
            "kind": 15,
            "detail": detail,
            "insertText": snippet,
            "insertTextFormat": 2,
            "sortText": "5",
        })
    send({"jsonrpc": "2.0", "id": request_id, "result": items})


def handle_hover(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, start, end = _word_position(text, line, character)
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return

    path = _source_path(uri)
    lines = _lines(text)
    current = lines[line] if 0 <= line < len(lines) else ""
    before = current[:start].rstrip()
    hover_range = {
        "start": {"line": line, "character": start},
        "end": {"line": line, "character": end},
    }

    def respond(value: str) -> None:
        send({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": {"kind": "markdown", "value": value},
                "range": hover_range,
            },
        })

    if before.endswith("."):
        dot_index = len(before) - 1
        object_name = _object_name_before_dot(current, dot_index)
        index = build_document_index(text, path)
        object_symbols = index["by_name"].get(object_name, [])
        object_symbol = object_symbols[0] if object_symbols else None
        if object_symbol and object_symbol["kind"] == "module":
            module_index = _module_index_for(object_symbol, path)
            if module_index:
                members = module_index["by_name"].get(word, [])
                if members:
                    respond(_symbol_markdown(members[0]))
                    return
        elif object_symbol:
            property_symbol = index["properties"].get((object_symbol.get("type", ""), word))
            if property_symbol:
                respond(_symbol_markdown(property_symbol))
                return
        respond(f"**property** `{word}`")
        return

    if word == "error" and current[end:].lstrip().startswith("("):
        signature, documentation = BUILTIN_DOCS["error"]
        respond(f"**builtin function** `{signature}`\n\n{documentation}")
        return
    if word in BUILTIN_TYPE_DOCS:
        respond(f"**builtin type** `{word}`\n\n{BUILTIN_TYPE_DOCS[word]}")
        return
    if word in BUILTIN_DOCS:
        signature, documentation = BUILTIN_DOCS[word]
        respond(f"**builtin function** `{signature}`\n\n{documentation}")
        return
    if word in CONSTANT_DOCS:
        respond(f"**constant** `{word}`\n\n{CONSTANT_DOCS[word]}")
        return
    if word in KEYWORD_DOCS:
        respond(f"**keyword** `{word}`\n\n{KEYWORD_DOCS[word]}")
        return

    index = build_document_index(text, path)
    symbols = index["by_name"].get(word, [])
    if symbols:
        respond(_symbol_markdown(symbols[0]))
        return

    respond(f"`{word}`")


def _location(uri, line, character, length=1):
    return {
        "uri": uri,
        "range": {
            "start": {"line": line, "character": character},
            "end": {"line": line, "character": character + length},
        },
    }


def handle_definition(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, _, _ = _word_position(text, line, character)
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    symbol, index = _resolve_symbol(text, word, line, character, _source_path(uri))
    locations = []
    if symbol:
        target_uri = index.get("uri") or uri
        locations.append(_location(target_uri, symbol["line"], symbol["col"], max(1, symbol["end_col"] - symbol["col"])))
    else:
        current_index = build_document_index(text, _source_path(uri))
        for candidate in current_index["by_name"].get(word, []):
            locations.append(_location(uri, candidate["line"], candidate["col"], max(1, candidate["end_col"] - candidate["col"])))
    send({"jsonrpc": "2.0", "id": request_id, "result": locations or None})


def handle_declaration(request_id, params) -> None:
    handle_definition(request_id, params)


def handle_type_definition(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, _, _ = _word_position(text, line, character)
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    symbol, index = _resolve_symbol(text, word, line, character, _source_path(uri))
    if not symbol:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    type_name = symbol.get("type", "")
    # For variables, functions and parameters, resolve the type name.
    type_word = None
    if symbol["kind"] in {"variable", "parameter", "function", "method", "property"}:
        type_word = type_name
    elif symbol["kind"] == "type":
        type_word = symbol["name"]
    if not type_word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    identifiers = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", type_word)
    target_symbol = None
    target_index = index
    for identifier in identifiers:
        candidates = index["by_name"].get(identifier, [])
        for candidate in candidates:
            if candidate["kind"] == "type":
                target_symbol = candidate
                break
        if target_symbol:
            break
    if not target_symbol:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    target_uri = target_index.get("uri") or uri
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": _location(target_uri, target_symbol["line"], target_symbol["col"], max(1, target_symbol["end_col"] - target_symbol["col"])),
    })


SYMBOL_KINDS = {
    "function": 12,
    "method": 6,
    "type": 5,
    "const": 14,
    "variable": 13,
    "parameter": 13,
    "property": 7,
    "module": 2,
}


def _document_symbol_node(symbol: dict, index: dict, children: list[dict] | None = None) -> dict:
    lines = index["lines"]
    line = symbol["line"]
    line_text = lines[line] if 0 <= line < len(lines) else ""
    node = {
        "name": symbol["name"],
        "detail": symbol.get("type", ""),
        "kind": SYMBOL_KINDS.get(symbol["kind"], 13),
        "range": {
            "start": {"line": line, "character": 0},
            "end": {"line": line, "character": len(line_text)},
        },
        "selectionRange": {
            "start": {"line": line, "character": symbol["col"]},
            "end": {"line": line, "character": symbol["end_col"]},
        },
    }
    if children:
        node["children"] = children
    return node


def handle_document_symbol(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    index = build_document_index(text, _source_path(uri))
    top_level: list[dict] = []
    children_by_container: dict[str, list[dict]] = {}
    for symbol in index["symbols"]:
        container = symbol.get("container")
        if container:
            children_by_container.setdefault(container, []).append(symbol)
    for symbol in index["symbols"]:
        if symbol.get("container"):
            continue
        children = [
            _document_symbol_node(child, index)
            for child in sorted(children_by_container.get(symbol["name"], []), key=lambda item: item["line"])
            if child["kind"] != "parameter"
        ]
        top_level.append(_document_symbol_node(symbol, index, children))
    top_level.sort(key=lambda item: item["range"]["start"]["line"])
    send({"jsonrpc": "2.0", "id": request_id, "result": top_level})


def _workspace_documents():
    seen: set[str] = set()
    for uri, text in DOCUMENTS.items():
        seen.add(uri)
        yield uri, text, _source_path(uri)
    if WORKSPACE_ROOT:
        root = Path(WORKSPACE_ROOT)
        if root.exists():
            for path in root.rglob("*.po"):
                uri = path.resolve().as_uri()
                if uri in seen:
                    continue
                seen.add(uri)
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                yield uri, text, str(path)


def handle_workspace_symbol(request_id, params) -> None:
    query = (params.get("query") or "").lower()
    results: list[dict] = []
    for uri, text, path in _workspace_documents():
        index = build_document_index(text, path)
        for symbol in index["symbols"]:
            if symbol["kind"] == "parameter":
                continue
            if query and query not in symbol["name"].lower():
                continue
            results.append({
                "name": symbol["name"],
                "kind": SYMBOL_KINDS.get(symbol["kind"], 13),
                "containerName": symbol.get("container", ""),
                "location": _location(uri, symbol["line"], symbol["col"], max(1, symbol["end_col"] - symbol["col"])),
            })
            if len(results) >= 200:
                break
        if len(results) >= 200:
            break
    send({"jsonrpc": "2.0", "id": request_id, "result": results})


def _identifier_occurrences(text: str, name: str) -> list[tuple[int, int, int]]:
    tokens = _scan_semantic_tokens(text)
    return [
        (token["line"], token["col"], len(token["value"]))
        for token in tokens
        if token["kind"] == "identifier" and token["value"] == name
    ]


def handle_references(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, _, _ = _word_position(text, line, character)
    if not word or word in KEYWORDS or word in BUILTINS or word in BUILTIN_TYPES:
        send({"jsonrpc": "2.0", "id": request_id, "result": []})
        return
    results: list[dict] = []
    for doc_uri, doc_text, _ in _workspace_documents():
        for ref_line, ref_col, ref_length in _identifier_occurrences(doc_text, word):
            results.append(_location(doc_uri, ref_line, ref_col, ref_length))
    send({"jsonrpc": "2.0", "id": request_id, "result": results})


def handle_prepare_rename(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, start, end = _word_position(text, line, character)
    if not word or word in KEYWORDS or word in BUILTINS or word in BUILTIN_TYPES:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "range": {
                "start": {"line": line, "character": start},
                "end": {"line": line, "character": end},
            },
            "placeholder": word,
        },
    })


def handle_rename(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, _, _ = _word_position(text, line, character)
    new_name = params.get("newName", "")
    if not word or not new_name or word in KEYWORDS or word in BUILTINS or word in BUILTIN_TYPES:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    changes: dict[str, list[dict]] = {}
    for doc_uri, doc_text, _ in _workspace_documents():
        edits = []
        for ref_line, ref_col, ref_length in _identifier_occurrences(doc_text, word):
            edits.append({
                "range": {
                    "start": {"line": ref_line, "character": ref_col},
                    "end": {"line": ref_line, "character": ref_col + ref_length},
                },
                "newText": new_name,
            })
        if edits:
            changes[doc_uri] = edits
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {"changes": changes} if changes else None,
    })


def handle_document_highlight(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    word, _, _ = _word_position(text, line, character)
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": []})
        return
    lines = _lines(text)
    highlights = []
    for ref_line, ref_col, ref_length in _identifier_occurrences(text, word):
        line_text = lines[ref_line] if 0 <= ref_line < len(lines) else ""
        after = line_text[ref_col + ref_length:]
        kind = 3 if re.match(r"^\s*(?::=|[+\-*/]?=)", after) else 2
        highlights.append({
            "range": {
                "start": {"line": ref_line, "character": ref_col},
                "end": {"line": ref_line, "character": ref_col + ref_length},
            },
            "kind": kind,
        })
    send({"jsonrpc": "2.0", "id": request_id, "result": highlights})


def handle_formatting(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    lines = _lines(text)
    new_text = _format_text(text)
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": [{
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": len(lines), "character": 0},
            },
            "newText": new_text,
        }],
    })


def _format_text(text: str) -> str:
    lines = _lines(text)
    result = []
    indent = 0
    blank_pending = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_pending += 1
            continue
        if stripped.startswith("}"):
            indent = max(0, indent - 1)
        # ensure at most two blank lines between top-level blocks
        if result and stripped.startswith(("fun ", "type ", "const ", "use ", "export ")):
            # ensure two blank lines before top-level decl
            while len(result) > 0 and result[-1] == "":
                result.pop()
            result.append("")
            result.append("")
        if blank_pending:
            # collapse multiple blanks to one inside
            result.append("")
            blank_pending = 0
        result.append("    " * indent + stripped)
        if stripped.endswith("{"):
            indent += 1
    # final newline
    new_text = "\n".join(result).rstrip("\n") + "\n"
    return new_text


def handle_range_formatting(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    rng = params.get("range", {})
    start_line = rng.get("start", {}).get("line", 0)
    end_line = rng.get("end", {}).get("line", 0)
    lines = _lines(text)
    # Format whole doc then slice changed region lines.
    formatted = _format_text(text).split("\n")
    # Build edit replacing selected range with formatted selected lines.
    selected_original = lines[start_line:end_line + 1]
    selected_formatted = formatted[start_line:min(end_line + 1, len(formatted))]
    new_text = "\n".join(selected_formatted)
    old_text = "\n".join(selected_original)
    if new_text == old_text:
        send({"jsonrpc": "2.0", "id": request_id, "result": []})
        return
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": [{
            "range": {
                "start": {"line": start_line, "character": 0},
                "end": {"line": end_line, "character": len(lines[end_line]) if end_line < len(lines) else 0},
            },
            "newText": new_text,
        }],
    })


def handle_code_action(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    lines = _lines(text)
    context = params.get("context", {})
    diagnostics = context.get("diagnostics", [])
    rng = params.get("range", {})
    actions = []

    # Quick fixes for removable diagnostics
    for diag in diagnostics:
        code = diag.get("code")
        r = diag.get("range", {})
        start = r.get("start", {})
        end = r.get("end", {})
        sl = start.get("line", 0)
        sc = start.get("character", 0)
        el = end.get("line", 0)
        ec = end.get("character", 0)
        if code in ("PW001", "PW002", "PW004", "PW009"):
            # remove the whole line
            line_text = lines[sl] if sl < len(lines) else ""
            actions.append({
                "title": f"Remove line ({code})",
                "kind": "quickfix",
                "diagnostics": [diag],
                "edit": {
                    "changes": {
                        uri: [{
                            "range": {
                                "start": {"line": sl, "character": 0},
                                "end": {"line": sl + 1, "character": 0},
                            },
                            "newText": "",
                        }]
                    }
                },
            })


    # Organize imports
    actions.append({
        "title": "Organize imports",
        "kind": "source.organizeImports",
        "edit": {
            "changes": {
                uri: _organize_imports_edits(text, uri)
            }
        },
    })

    # Fix all safe
    actions.append({
        "title": "Fix all auto-fixable problems",
        "kind": "source.fixAll",
        "edit": {
            "changes": {
                uri: _fix_all_edits(text, uri)
            }
        },
    })

    # Apply formatting
    actions.append({
        "title": "Format document",
        "kind": "source",
        "command": {"title": "format", "command": "powang.formatDocument", "arguments": [uri]},
    })

    # Disable rule comment for first diagnostic
    if diagnostics:
        code = diagnostics[0].get("code")
        sl = diagnostics[0].get("range", {}).get("start", {}).get("line", 0)
        actions.append({
            "title": f"Disable {code} for this line",
            "kind": "quickfix",
            "diagnostics": [diagnostics[0]],
            "edit": {
                "changes": {
                    uri: [{
                        "range": {
                            "start": {"line": sl, "character": len(lines[sl]) if sl < len(lines) else 0},
                            "end": {"line": sl, "character": len(lines[sl]) if sl < len(lines) else 0},
                        },
                        "newText": f"  ## noqa: {code}",
                    }]
                }
            },
        })

    send({"jsonrpc": "2.0", "id": request_id, "result": actions})


def _organize_imports_edits(text: str, uri: str) -> list[dict]:
    lines = _lines(text)
    use_indices = [i for i, l in enumerate(lines) if l.strip().startswith("use ")]
    if not use_indices:
        return []
    # collect import lines, sort, replace block
    block_start = use_indices[0]
    block_end = use_indices[-1]
    import_lines = [lines[i].strip() for i in use_indices]
    import_lines_sorted = sorted(set(import_lines))
    # remove original import lines (mark empty)
    new_lines = list(lines)
    for i in use_indices:
        new_lines[i] = None  # type: ignore
    # rebuild
    rebuilt = [l for l in new_lines if l is not None]
    # insert sorted imports at block_start position (approx)
    # Simpler: produce full new text
    # We'll just replace range block_start..block_end
    replacement = "\n".join(import_lines_sorted)
    return [{
        "range": {
            "start": {"line": block_start, "character": 0},
            "end": {"line": block_end, "character": len(lines[block_end])},
        },
        "newText": replacement,
    }]


def _fix_all_edits(text: str, uri: str) -> list[dict]:
    # Remove lines with unused imports/vars and trailing whitespace; sort imports.
    lines = _lines(text)
    to_remove: set[int] = set()
    # unused imports
    imported_names = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        m = re.match(r"^use\s+(?:\"[^\"]+\"|([A-Za-z_][A-Za-z0-9_]*))(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*|\*))?", stripped)
        if m:
            name = m.group(2) or m.group(1)
            if name and name != "*":
                imported_names.append((index, name))
    for import_line, name in imported_names:
        occurrences = 0
        for li, line in enumerate(lines):
            if li == import_line:
                continue
            occurrences += len(re.findall(r"\b" + re.escape(name) + r"\b", line))
        if occurrences == 0:
            to_remove.add(import_line)
    # unused vars
    declared = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        cm = re.match(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)", stripped)
        if cm:
            declared.append((index, cm.group(1)))
            continue
        vm = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?\s*(?::=|=)", stripped)
        if vm and vm.group(1) not in KEYWORDS:
            declared.append((index, vm.group(1)))
    for decl_line, name in declared:
        occurrences = 0
        for li, line in enumerate(lines):
            if li == decl_line:
                continue
            occurrences += len(re.findall(r"\b" + re.escape(name) + r"\b", line))
        if occurrences == 0:
            to_remove.add(decl_line)

    # trailing whitespace fix: edit in place (handled by line replacement)
    edits = []
    # Remove lines from bottom to top
    for idx in sorted(to_remove, reverse=True):
        edits.append({
            "range": {
                "start": {"line": idx, "character": 0},
                "end": {"line": idx + 1, "character": 0},
            },
            "newText": "",
        })
    # trailing whitespace edits
    for idx, line in enumerate(lines):
        if line != line.rstrip(" \t") and idx not in to_remove:
            edits.append({
                "range": {
                    "start": {"line": idx, "character": len(line.rstrip(" \t"))},
                    "end": {"line": idx, "character": len(line)},
                },
                "newText": "",
            })
    return edits


def _parameters_from_signature(signature: str) -> list[str]:
    open_index = signature.find("(")
    if open_index < 0:
        return []
    depth = 0
    close_index = -1
    for index in range(open_index, len(signature)):
        char = signature[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index < 0:
        return []
    return _split_top_level(signature[open_index + 1:close_index], ",")


def _signature_symbols(text: str, callee: str, line: int, character: int, path: str | None) -> list[dict]:
    index = build_document_index(text, path)
    if "." in callee:
        object_name, member_name = callee.rsplit(".", 1)
        object_symbols = index["by_name"].get(object_name, [])
        object_symbol = object_symbols[0] if object_symbols else None
        if object_symbol and object_symbol["kind"] == "module":
            module_index = _module_index_for(object_symbol, path)
            if module_index:
                return [
                    symbol for symbol in module_index["by_name"].get(member_name, [])
                    if symbol["kind"] in {"function", "method"}
                ]
        elif object_symbol:
            property_symbol = index["properties"].get((object_symbol.get("type", ""), member_name))
            if property_symbol and property_symbol["kind"] == "method":
                return [property_symbol]
        return []
    symbols = [
        symbol for symbol in index["by_name"].get(callee, [])
        if symbol["kind"] in {"function", "method"}
    ]
    if symbols:
        return symbols
    if callee in BUILTIN_DOCS:
        signature, documentation = BUILTIN_DOCS[callee]
        return [{
            "name": callee,
            "kind": "function",
            "signature": signature,
            "documentation": documentation,
            "type": "any",
        }]
    return []


def handle_signature_help(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    line = pos.get("line", 0)
    character = pos.get("character", 0)
    lines = _lines(text)
    current = lines[line] if 0 <= line < len(lines) else ""
    before = current[:character]

    open_index = -1
    depth = 0
    in_string = False
    escape = False
    for index in range(len(before) - 1, -1, -1):
        char = before[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                open_index = index
                break
            depth -= 1
    if open_index < 0:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return

    cursor = open_index - 1
    while cursor >= 0 and before[cursor].isspace():
        cursor -= 1
    end = cursor + 1
    while cursor >= 0 and (before[cursor].isalnum() or before[cursor] in "_."):
        cursor -= 1
    callee = before[cursor + 1:end]
    if not callee:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return

    active_parameter = 0
    depth = 0
    in_string = False
    escape = False
    for char in before[open_index + 1:]:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            active_parameter += 1

    symbols = _signature_symbols(text, callee, line, character, _source_path(uri))
    if not symbols:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    signatures = []
    for symbol in symbols:
        signature = symbol.get("signature", symbol.get("name", callee))
        parameters = _parameters_from_signature(signature)
        signatures.append({
            "label": signature,
            "documentation": {
                "kind": "markdown",
                "value": symbol.get("documentation", ""),
            },
            "parameters": [{"label": parameter} for parameter in parameters],
        })
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "signatures": signatures,
            "activeSignature": 0,
            "activeParameter": max(0, active_parameter),
        },
    })


def handle_inlay_hint(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    hint_range = params.get("range", {})
    start_line = hint_range.get("start", {}).get("line", 0)
    end_line = hint_range.get("end", {}).get("line", 10**9)
    index = build_document_index(text, _source_path(uri))
    hints = []
    for symbol in index["symbols"]:
        if symbol["kind"] != "variable" or symbol.get("annotated"):
            continue
        if symbol["type"] in {"any", "nova", ""}:
            continue
        line_text = lines[symbol["line"]] if symbol["line"] < len(lines) else ""
        # Only show the ghost type for inferred declarations (:=), not for
        # assignments to an existing variable.
        if ":=" not in line_text:
            continue
        if symbol["line"] < start_line or symbol["line"] > end_line:
            continue
        hints.append({
            "position": {"line": symbol["line"], "character": symbol["end_col"]},
            "label": f": {symbol['type']}",
            "kind": 1,
            "paddingLeft": False,
            "paddingRight": False,
        })
    send({"jsonrpc": "2.0", "id": request_id, "result": hints})


def handle_folding_range(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    lines = _lines(text)
    ranges: list[dict] = []

    index = 0
    while index < len(lines):
        if lines[index].strip().startswith("#!"):
            start = index
            while index < len(lines) and "!#" not in lines[index]:
                index += 1
            if index < len(lines):
                ranges.append({"startLine": start, "endLine": index, "kind": "comment"})
        index += 1

    index = 0
    while index < len(lines):
        if lines[index].strip().startswith("##"):
            start = index
            while index + 1 < len(lines) and lines[index + 1].strip().startswith("##"):
                index += 1
            if index > start:
                ranges.append({"startLine": start, "endLine": index, "kind": "comment"})
        index += 1

    stack: list[int] = []
    for token in _scan_semantic_tokens(text):
        if token["kind"] != "operator":
            continue
        if token["value"] == "{":
            stack.append(token["line"])
        elif token["value"] == "}" and stack:
            start = stack.pop()
            if token["line"] > start:
                ranges.append({"startLine": start, "endLine": token["line"], "kind": "region"})
    send({"jsonrpc": "2.0", "id": request_id, "result": ranges})


def _scan_semantic_tokens(text: str) -> list[dict]:
    tokens: list[dict] = []
    line = 0
    col = 0
    i = 0
    n = len(text)
    multi_ops = (
        ">>", "|>", "?.", "??", "==", "!=", "<=", ">=",
        "&&", "||", "::", "!:", "+=", "-=", "*=", "/=",
    )
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            col = 0
            i += 1
            continue

        if text.startswith("#!", i):
            start_line, start_col = line, col
            end = text.find("!#", i + 2)
            end = n if end == -1 else end + 2
            value = text[i:end]
            tokens.append({"kind": "comment", "value": value, "line": start_line, "col": start_col})
            for char in value:
                if char == "\n":
                    line += 1
                    col = 0
                else:
                    col += 1
            i = end
            continue

        if text.startswith("##", i):
            start_line, start_col = line, col
            end = text.find("\n", i)
            end = n if end == -1 else end
            value = text[i:end]
            tokens.append({"kind": "comment", "value": value, "line": start_line, "col": start_col})
            col += len(value)
            i = end
            continue

        if ch == '"' or (ch == "$" and i + 1 < n and text[i + 1] == '"'):
            start_line, start_col = line, col
            start = i
            if ch == "$":
                i += 1
                col += 1
            i += 1
            col += 1
            while i < n:
                current = text[i]
                if current == "\\" and i + 1 < n:
                    i += 2
                    col += 2
                    continue
                if current == '"':
                    i += 1
                    col += 1
                    break
                if current == "\n":
                    line += 1
                    col = 0
                    i += 1
                    continue
                i += 1
                col += 1
            tokens.append({"kind": "string", "value": text[start:i], "line": start_line, "col": start_col})
            continue

        if ch.isalpha() or ch == "_":
            start = i
            start_line, start_col = line, col
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
                col += 1
            tokens.append({"kind": "identifier", "value": text[start:i], "line": start_line, "col": start_col})
            continue

        if ch.isdigit():
            start = i
            start_line, start_col = line, col
            while i < n and (
                text[i].isdigit()
                or text[i] in ".eE"
                or (text[i] in "+-" and i > start and text[i - 1] in "eE")
            ):
                i += 1
                col += 1
            tokens.append({"kind": "number", "value": text[start:i], "line": start_line, "col": start_col})
            continue

        matched = None
        for operator in multi_ops:
            if text.startswith(operator, i):
                matched = operator
                break
        if matched is not None:
            tokens.append({"kind": "operator", "value": matched, "line": line, "col": col})
            i += len(matched)
            col += len(matched)
            continue

        if ch in "{}()[],;.+-*/%=&|<>!?:@":
            tokens.append({"kind": "operator", "value": ch, "line": line, "col": col})
            i += 1
            col += 1
            continue

        i += 1
        col += 1
    return tokens


def _classify_semantic_tokens(tokens: list[dict]) -> None:
    user_types: set[str] = set()
    functions: set[str] = set()
    macros: set[str] = set()
    modules: set[str] = set()
    declarations: dict[int, str] = {}

    for index, token in enumerate(tokens):
        if token["kind"] != "identifier":
            continue
        word = token["value"]
        previous = tokens[index - 1] if index > 0 else None
        previous_word = previous["value"] if previous and previous["kind"] == "identifier" else None
        if previous_word == "fun":
            functions.add(word)
            declarations[index] = "function"
        elif previous_word == "type":
            user_types.add(word)
            declarations[index] = "type"
        elif previous_word == "const":
            macros.add(word)
            declarations[index] = "macro"
        elif previous_word == "use":
            modules.add(word)
            declarations[index] = "namespace"
        elif previous_word == "as":
            modules.add(word)
            declarations[index] = "namespace"

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token["kind"] == "identifier" and token["value"] == "fun":
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor]["kind"] != "identifier":
                cursor += 1
            while cursor < len(tokens) and tokens[cursor]["value"] != "(":
                cursor += 1
            if cursor >= len(tokens):
                break
            depth = 0
            cursor += 1
            while cursor < len(tokens):
                current = tokens[cursor]
                if current["value"] == "(":
                    depth += 1
                elif current["value"] == ")":
                    if depth == 0:
                        break
                    depth -= 1
                elif current["kind"] == "identifier" and depth == 0:
                    next_index = cursor + 1
                    while next_index < len(tokens) and tokens[next_index]["kind"] == "comment":
                        next_index += 1
                    if next_index < len(tokens) and tokens[next_index]["value"] == ":":
                        if current["value"] not in BUILTIN_TYPES and current["value"] not in user_types:
                            declarations[cursor] = "parameter"
                cursor += 1
            index = cursor
        index += 1

    for token_index, token in enumerate(tokens):
        kind = token["kind"]
        if kind == "comment":
            token["semantic"] = "comment"
            continue
        if kind == "string":
            token["semantic"] = "string"
            continue
        if kind == "number":
            token["semantic"] = "number"
            continue
        if kind == "operator":
            token["semantic"] = "operator"
            continue
        if kind != "identifier":
            continue

        word = token["value"]
        if token_index in declarations:
            token["semantic"] = declarations[token_index]
            continue
        if word in KEYWORDS or word == "this":
            token["semantic"] = "keyword"
            continue
        if word in BUILTINS:
            token["semantic"] = "builtin"
            continue
        if word in BUILTIN_TYPES:
            token["semantic"] = "builtinType"
            continue
        if word in user_types:
            token["semantic"] = "type"
            continue
        if word in modules:
            token["semantic"] = "namespace"
            continue
        if word in macros:
            token["semantic"] = "macro"
            continue
        if word in functions:
            token["semantic"] = "function"
            continue
        if word in ("true", "false", "nova"):
            token["semantic"] = "constant"
            continue

        previous = tokens[token_index - 1] if token_index > 0 else None
        following = tokens[token_index + 1] if token_index + 1 < len(tokens) else None
        if previous and previous["value"] == ".":
            token["semantic"] = "method" if following and following["value"] == "(" else "property"
            continue
        if following and following["value"] == "(":
            token["semantic"] = "function"
            continue
        token["semantic"] = "variable"


def _encode_semantic_tokens(tokens: list[dict]) -> list[int]:
    data: list[int] = []
    previous_line = 0
    previous_char = 0
    for token in tokens:
        semantic = token.get("semantic")
        if semantic is None:
            continue
        type_index = SEMANTIC_TYPE_INDEX[semantic]
        value = token["value"]
        start_line = token["line"]
        start_col = token["col"]
        if "\n" in value:
            for part in value.split("\n"):
                if part:
                    delta_line = start_line - previous_line
                    delta_char = start_col if delta_line > 0 else start_col - previous_char
                    data.extend([delta_line, delta_char, len(part), type_index, 0])
                    previous_line = start_line
                    previous_char = start_col
                start_line += 1
                start_col = 0
        else:
            delta_line = start_line - previous_line
            delta_char = start_col if delta_line > 0 else start_col - previous_char
            data.extend([delta_line, delta_char, len(value), type_index, 0])
            previous_line = start_line
            previous_char = start_col
    return data


def handle_semantic_tokens(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    tokens = _scan_semantic_tokens(text)
    _classify_semantic_tokens(tokens)
    send({"jsonrpc": "2.0", "id": request_id, "result": {"data": _encode_semantic_tokens(tokens)}})


def dispatch(message: dict) -> bool:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        handle_initialize(request_id, params)
    elif method == "initialized":
        pass
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
    elif method == "exit":
        return False
    elif method == "textDocument/didOpen":
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        text = doc.get("text", "")
        if uri is not None:
            DOCUMENTS[uri] = text
            diagnose(uri, text)
    elif method == "textDocument/didChange":
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        changes = params.get("contentChanges", [])
        if uri is not None and changes:
            DOCUMENTS[uri] = changes[-1].get("text", "")
            diagnose(uri, DOCUMENTS[uri])
    elif method == "textDocument/didSave":
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        if uri in DOCUMENTS:
            diagnose(uri, DOCUMENTS[uri])
    elif method == "textDocument/didClose":
        doc = params.get("textDocument", {})
        uri = doc.get("uri")
        DOCUMENTS.pop(uri, None)
    elif method == "textDocument/completion":
        handle_completion(request_id, params)
    elif method == "textDocument/hover":
        handle_hover(request_id, params)
    elif method == "textDocument/signatureHelp":
        handle_signature_help(request_id, params)
    elif method == "textDocument/definition":
        handle_definition(request_id, params)
    elif method == "textDocument/declaration":
        handle_declaration(request_id, params)
    elif method == "textDocument/typeDefinition":
        handle_type_definition(request_id, params)
    elif method == "textDocument/documentHighlight":
        handle_document_highlight(request_id, params)
    elif method == "textDocument/documentSymbol":
        handle_document_symbol(request_id, params)
    elif method == "workspace/symbol":
        handle_workspace_symbol(request_id, params)
    elif method == "textDocument/references":
        handle_references(request_id, params)
    elif method == "textDocument/prepareRename":
        handle_prepare_rename(request_id, params)
    elif method == "textDocument/rename":
        handle_rename(request_id, params)
    elif method == "textDocument/formatting":
        handle_formatting(request_id, params)
    elif method == "textDocument/rangeFormatting":
        handle_range_formatting(request_id, params)
    elif method == "textDocument/codeAction":
        handle_code_action(request_id, params)
    elif method == "workspace/executeCommand":
        cmd = params.get("command")
        if cmd == "powang.formatDocument":
            uri = (params.get("arguments") or [""])[0]
            text = DOCUMENTS.get(uri, "")
            new_text = _format_text(text)
            DOCUMENTS[uri] = new_text
            diagnose(uri, new_text)
            send({"jsonrpc": "2.0", "id": request_id, "result": None})
        else:
            send({"jsonrpc": "2.0", "id": request_id, "result": None})
    elif method == "textDocument/inlayHint":
        handle_inlay_hint(request_id, params)
    elif method == "textDocument/foldingRange":
        handle_folding_range(request_id, params)
    elif method == "textDocument/semanticTokens/full":
        handle_semantic_tokens(request_id, params)
    else:
        if request_id is not None:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            })
    return True


def main() -> None:
    while True:
        message = read_message()
        if message is None:
            break
        request_id = message.get("id")
        try:
            keep_running = dispatch(message)
        except Exception as error:  # noqa: BLE001 - never crash the server
            if request_id is not None:
                send({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": f"internal error: {error}"},
                })
            else:
                send({
                    "jsonrpc": "2.0",
                    "method": "window/logMessage",
                    "params": {"type": 1, "message": f"powang-lsp internal error: {error}"},
                })
            keep_running = True
        if not keep_running:
            break


if __name__ == "__main__":
    main()