"""Smoke checks for the bundled powang language server.

Run with `python lsp_smoke.py` from the powang-lsp repository root. The script
loads the server module directly and exercises the pure helpers that power
inlay hints, inline completion, code actions and diagnostics.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent / "server" / "powang_lsp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("powang_lsp_smoke", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    server = load_server()
    text = (
        "type Person[+] {\n"
        "    | name: str;\n"
        "    | address: str;\n"
        "\n"
        "    fun constructor {\n"
        "        print(this.name);\n"
        "    }\n"
        "}\n"
        "\n"
        'person := Person.["Ada", "London"];\n'
    )
    lines = text.split("\n")
    index = server.build_document_index(text, None)
    people = [symbol for symbol in index["symbols"] if symbol["name"] == "Person"]
    assert people and people[0].get("constructor_parameters") == ["name", "address"], people

    hints = server._constructor_inlay_hints(text, index, 0, len(lines))
    labels = [hint["label"] for hint in hints]
    assert labels == ["name: ", "address: "], labels

    completion = server._inline_completion_items(lines, 0, "type Person")
    assert any(item["label"] == "[+]" for item in completion), completion
    completion = server._inline_completion_items(lines, 4, "    fun ")
    assert any(item["label"] == "constructor" for item in completion), completion

    actions = server._constructor_code_actions(text, "file:///person.po", lines, 1, [])
    titles = {action["title"] for action in actions}
    assert "Make member private" in titles, titles
    assert "Make member public" not in titles, titles
    actions = server._constructor_code_actions(text, "file:///person.po", lines, 9, [])
    assert any(action["title"] == "Convert to named arguments" for action in actions), actions

    multiline = (
        "type T[+] {\n"
        "    | a: int;\n"
        "    fun helper() {\n"
        '        print("}");\n'
        "    }\n"
        "    | b: str;  ## second\n"
        "}\n"
    )
    multiline_index = server.build_document_index(multiline, None)
    types = [symbol for symbol in multiline_index["symbols"] if symbol["kind"] == "type"]
    assert types and types[0].get("constructor_parameters") == ["a", "b"], types

    false_positive = 'type Person[+] { | name: str; }\nmsg := "Person.[1]"; ## Person.[2]\n'
    false_index = server.build_document_index(false_positive, None)
    assert server._constructor_inlay_hints(false_positive, false_index, 0, 10) == [], "hint in string or comment"

    member_completion = server._inline_completion_items(["    |"], 0, "    |")
    assert all(not item.get("insertText", "").startswith("|") for item in member_completion), member_completion

    assert "&src: arr[T]" in server._native_signature("arr", "push"), server._native_signature("arr", "push")
    resolved, _ = server._resolve_symbol(
        'values := [1];\nvalues.push(2);\n', "push", 1, 7, None
    )
    assert resolved and "value: T" in resolved.get("signature", ""), resolved

    messages: list[dict] = []
    server.send = messages.append
    broken = (
        "type Person[+] {\n"
        "    | name: str;\n"
        "    | address: str;\n"
        "}\n"
        'person := Person.["Ada"];\n'
        "print(person.name);\n"
    )
    server.diagnose("file:///broken.po", broken)
    diagnostics = messages[-1]["params"]["diagnostics"]
    missing = [
        diagnostic for diagnostic in diagnostics
        if "missing required argument 'address'" in diagnostic["message"]
    ]
    assert missing, diagnostics
    assert missing[0]["range"]["start"]["line"] == 4, missing[0]["range"]
    assert missing[0].get("relatedInformation"), missing[0]

    warning_messages: list[dict] = []
    server.send = warning_messages.append
    server.diagnose(
        "file:///warning.po",
        "type T[+] {\n    + value: int;\n}\nitem := T.[];\n",
    )
    warnings = [
        diagnostic for diagnostic in warning_messages[-1]["params"]["diagnostics"]
        if diagnostic.get("code") == "PW201"
    ]
    assert warnings and warnings[0]["range"]["start"]["line"] == 1, warnings

    print("lsp smoke: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
