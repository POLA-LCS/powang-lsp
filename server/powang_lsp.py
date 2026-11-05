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

ROOT = Path(os.environ.get("POWANG_REPO", Path.cwd())).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser import Parser  # noqa: E402
from src.typecheck import check_source  # noqa: E402

KEYWORDS = [
    "if", "else", "for", "fun", "return", "use", "type", "extern",
    "try", "catch", "finally", "spawn", "export", "match", "case", "const",
]

BUILTINS = [
    "print", "println", "format", "printf", "error", "fail", "input", "inputf", "typeof", "size",
    "open", "write", "read", "close", "system", "wait", "cancel", "task_status",
]

DOCUMENTS: dict[str, str] = {}


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


def diagnose(uri: str, text: str) -> None:
    diagnostics: list[dict] = []
    source_path = _source_path(uri)
    try:
        parser = Parser(text, source_path=source_path)
        parser.parse()
    except Exception as error:
        diagnostics.append({
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 1},
            },
            "severity": 1,
            "source": "powang",
            "message": str(error),
        })
    else:
        try:
            for type_error in check_source(text, source_path):
                diagnostics.append({
                    "range": {
                        "start": {"line": _line_number(type_error), "character": 0},
                        "end": {"line": _line_number(type_error), "character": 1},
                    },
                    "severity": 1,
                    "source": "powang",
                    "message": str(type_error),
                })
        except Exception as error:  # noqa: BLE001
            diagnostics.append({
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 1},
                },
                "severity": 2,
                "source": "powang",
                "message": f"internal checker error: {error}",
            })

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


def word_at(text: str, line: int, character: int) -> str:
    lines = _lines(text)
    if line < 0 or line >= len(lines):
        return ""
    current = lines[line]
    character = max(0, min(character, len(current)))
    start = character
    while start > 0 and (current[start - 1].isalnum() or current[start - 1] == "_"):
        start -= 1
    end = character
    while end < len(current) and (current[end].isalnum() or current[end] == "_"):
        end += 1
    return current[start:end]


def range_of_word(text: str, line: int, word: str) -> dict:
    lines = _lines(text)
    if line >= len(lines):
        return {"start": {"line": line, "character": 0}, "end": {"line": line, "character": len(word)}}
    current = lines[line]
    idx = current.find(word)
    if idx < 0:
        idx = 0
    return {"start": {"line": line, "character": idx}, "end": {"line": line, "character": idx + len(word)}}


DECL_RE = re.compile(r"^\s*(?:export\s+)?(?:fun|type)\s+([A-Za-z_][A-Za-z0-9_]*)")
VAR_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::=|:)")


def find_definitions(text: str, name: str) -> list[dict]:
    results = []
    for i, line in enumerate(_lines(text)):
        m = DECL_RE.match(line)
        if m and m.group(1) == name:
            results.append({"line": i, "name": name})
            continue
        m = VAR_RE.match(line)
        if m and m.group(1) == name:
            results.append({"line": i, "name": name})
    return results


def find_references(text: str, name: str) -> list[tuple[int, int]]:
    results = []
    for i, line in enumerate(_lines(text)):
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", line):
            results.append((i, m.start()))
    return results


def handle_initialize(request_id) -> None:
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "capabilities": {
                "textDocumentSync": 1,
                "completionProvider": {
                    "triggerCharacters": [".", ":"],
                },
                "hoverProvider": True,
                "definitionProvider": True,
                "declarationProvider": True,
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "referencesProvider": True,
                "renameProvider": True,
                "documentFormattingProvider": True,
                "semanticTokensProvider": {
                    "legend": {
                        "tokenTypes": ["keyword", "type", "function", "variable", "string", "number", "comment", "operator"],
                        "tokenModifiers": [],
                    },
                    "full": True,
                },
            },
            "serverInfo": {
                "name": "powang-lsp",
                "version": "0.4.0",
            },
        },
    })


def handle_completion(request_id, params) -> None:
    items = [
        {"label": name, "kind": 14, "detail": "keyword"}
        for name in KEYWORDS
    ] + [
        {"label": name, "kind": 3, "detail": "builtin"}
        for name in BUILTINS
    ]
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": items,
    })


def handle_hover(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    word = word_at(text, pos.get("line", 0), pos.get("character", 0))
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    if word in KEYWORDS:
        content = f"keyword: {word}"
    elif word in BUILTINS:
        content = f"builtin: {word}"
    else:
        content = f"identifier: {word}"
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "contents": {"kind": "plaintext", "value": content},
        },
    })


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
    word = word_at(text, pos.get("line", 0), pos.get("character", 0))
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    defs = find_definitions(text, word)
    if not defs:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    d = defs[0]
    rng = range_of_word(text, d["line"], word)
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": _location(uri, d["line"], rng["start"]["character"], len(word)),
    })


def handle_declaration(request_id, params) -> None:
    handle_definition(request_id, params)


def handle_document_symbol(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    symbols = []
    for i, line in enumerate(_lines(text)):
        m = DECL_RE.match(line)
        if m:
            name = m.group(1)
            kind = 5 if re.match(r"^\s*(?:export\s+)?type\b", line) else 12
            symbols.append({
                "name": name,
                "kind": kind,
                "range": {
                    "start": {"line": i, "character": 0},
                    "end": {"line": i, "character": len(line)},
                },
                "selectionRange": range_of_word(text, i, name),
            })
            continue
        m = VAR_RE.match(line)
        if m:
            name = m.group(1)
            if name in KEYWORDS:
                continue
            symbols.append({
                "name": name,
                "kind": 13,
                "range": {
                    "start": {"line": i, "character": 0},
                    "end": {"line": i, "character": len(line)},
                },
                "selectionRange": range_of_word(text, i, name),
            })
    send({"jsonrpc": "2.0", "id": request_id, "result": symbols})


def handle_workspace_symbol(request_id, params) -> None:
    query = params.get("query", "")
    results = []
    for uri, text in DOCUMENTS.items():
        for i, line in enumerate(_lines(text)):
            m = DECL_RE.match(line)
            if m:
                name = m.group(1)
                if query and query.lower() not in name.lower():
                    continue
                results.append({
                    "name": name,
                    "kind": 5 if re.match(r"^\s*(?:export\s+)?type\b", line) else 12,
                    "location": _location(uri, i, 0, len(line)),
                })
            m = VAR_RE.match(line)
            if m:
                name = m.group(1)
                if name in KEYWORDS:
                    continue
                if query and query.lower() not in name.lower():
                    continue
                results.append({
                    "name": name,
                    "kind": 13,
                    "location": _location(uri, i, 0, len(line)),
                })
    send({"jsonrpc": "2.0", "id": request_id, "result": results})


def handle_references(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    word = word_at(text, pos.get("line", 0), pos.get("character", 0))
    if not word:
        send({"jsonrpc": "2.0", "id": request_id, "result": []})
        return
    refs = find_references(text, word)
    result = []
    for (i, c) in refs:
        result.append(_location(uri, i, c, len(word)))
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def handle_rename(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    pos = params.get("position", {})
    word = word_at(text, pos.get("line", 0), pos.get("character", 0))
    new_name = params.get("newName", "")
    if not word or not new_name:
        send({"jsonrpc": "2.0", "id": request_id, "result": None})
        return
    edits = []
    for (i, c) in find_references(text, word):
        edits.append({
            "range": {
                "start": {"line": i, "character": c},
                "end": {"line": i, "character": c + len(word)},
            },
            "newText": new_name,
        })
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "changes": {uri: edits},
        },
    })


def handle_formatting(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    lines = _lines(text)
    result = []
    indent = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("}"):
            indent = max(0, indent - 1)
        result.append("    " * indent + stripped)
        if stripped.endswith("{"):
            indent += 1
    new_text = "\n".join(result)
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


def handle_semantic_tokens(request_id, params) -> None:
    text_doc = params.get("textDocument", {})
    uri = text_doc.get("uri")
    text = DOCUMENTS.get(uri, "")
    data = []
    prev_line = 0
    prev_char = 0
    for i, line in enumerate(_lines(text)):
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*|\d+|\"[^\"]*\"|##.*|[{}()\[\],;]|==|!=|<=|>=|&&|\|\||::|!:|>>|[+\-*/%=&|<>!?:@]", line):
            tok = m.group(0)
            if tok in KEYWORDS:
                ttype = 0
            elif tok in BUILTINS:
                ttype = 2
            elif tok.isdigit():
                ttype = 5
            elif tok.startswith('"'):
                ttype = 4
            elif tok.startswith("##"):
                ttype = 6
            else:
                ttype = 3
            delta_line = i - prev_line
            delta_char = m.start() if delta_line > 0 else m.start() - prev_char
            data.extend([delta_line, delta_char, len(tok), ttype, 0])
            prev_line = i
            prev_char = m.start()
    send({"jsonrpc": "2.0", "id": request_id, "result": {"data": data}})


def dispatch(message: dict) -> bool:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        handle_initialize(request_id)
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
    elif method == "textDocument/definition":
        handle_definition(request_id, params)
    elif method == "textDocument/declaration":
        handle_declaration(request_id, params)
    elif method == "textDocument/documentSymbol":
        handle_document_symbol(request_id, params)
    elif method == "workspace/symbol":
        handle_workspace_symbol(request_id, params)
    elif method == "textDocument/references":
        handle_references(request_id, params)
    elif method == "textDocument/rename":
        handle_rename(request_id, params)
    elif method == "textDocument/formatting":
        handle_formatting(request_id, params)
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