"""Safety checks for the language server capabilities."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "powang_lsp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("powang_lsp_capability_test", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = load_server()
        self.messages: list[dict] = []
        self.server.send = self.messages.append

    def test_destructive_capabilities_are_not_advertised(self) -> None:
        self.server.handle_initialize(1, {"capabilities": {}})
        capabilities = self.messages[-1]["result"]["capabilities"]
        self.assertNotIn("documentFormattingProvider", capabilities)
        self.assertNotIn("documentRangeFormattingProvider", capabilities)
        self.assertNotIn("executeCommandProvider", capabilities)
        self.assertEqual(
            capabilities["codeActionProvider"]["codeActionKinds"],
            ["quickfix"],
        )

    def test_code_actions_do_not_offer_source_edits(self) -> None:
        uri = "file:///safety.po"
        text = "x := 1;\n"
        self.server.DOCUMENTS[uri] = text
        self.server.handle_code_action(
            2,
            {
                "textDocument": {"uri": uri},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 1},
                },
                "context": {"diagnostics": []},
            },
        )
        actions = self.messages[-1]["result"]
        self.assertTrue(all(not action.get("kind", "").startswith("source") for action in actions))

    def test_formatting_request_is_method_not_found(self) -> None:
        self.server.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "textDocument/formatting",
                "params": {"textDocument": {"uri": "file:///safety.po"}},
            }
        )
        self.assertEqual(self.messages[-1]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
