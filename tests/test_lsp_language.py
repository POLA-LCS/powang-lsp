"""Loop labels, loop warnings and semantic tokens in the LSP."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "powang_lsp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("powang_lsp_language_test", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LanguageIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = load_server()
        self.messages: list[dict] = []
        self.server.send = self.messages.append

    def test_initialize_legend_has_label(self) -> None:
        self.server.handle_initialize(1, {"capabilities": {}})
        legend = self.messages[-1]["result"]["capabilities"]["semanticTokensProvider"]["legend"]["tokenTypes"]
        self.assertIn("label", legend)

    def test_document_index_tracks_loop_labels(self) -> None:
        index = self.server.build_document_index(
            "for |outer| i >> 0 >> 1 {\n    break outer;\n}\n",
            None,
        )
        self.assertEqual(index["labels"][0]["name"], "outer")
        self.assertEqual(index["labels"][0]["line"], 0)
        self.assertEqual(index["labels"][0]["end_line"], 2)

    def test_break_completion_suggests_active_labels(self) -> None:
        uri = "file:///labels.po"
        self.server.DOCUMENTS[uri] = "for |outer| i >> 0 >> 1 {\n    break \n}\n"
        self.server.handle_completion(
            2,
            {
                "textDocument": {"uri": uri},
                "position": {"line": 1, "character": 10},
            },
        )
        labels = [item["label"] for item in self.messages[-1]["result"]]
        self.assertIn("outer", labels)

    def test_loop_without_break_warns(self) -> None:
        uri = "file:///loop.po"
        self.server.diagnose(uri, 'loop {\n    print("x");\n}\n')
        diagnostics = self.messages[-1]["params"]["diagnostics"]
        self.assertTrue(
            any(d.get("code") == "PW210" for d in diagnostics),
            diagnostics,
        )

    def test_semantic_tokens_mark_labels(self) -> None:
        tokens = self.server._scan_semantic_tokens(
            "for |outer| i >> 0 >> 1 {\n    break outer;\n}\n"
        )
        self.server._classify_semantic_tokens(tokens)
        labels = [token["value"] for token in tokens if token.get("semantic") == "label"]
        self.assertEqual(labels, ["outer", "outer"])


if __name__ == "__main__":
    unittest.main()
