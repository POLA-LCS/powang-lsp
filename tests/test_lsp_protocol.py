"""JSON-RPC framing and shutdown safety tests."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server" / "powang_lsp.py"


def load_server():
    spec = importlib.util.spec_from_file_location("powang_lsp_protocol_test", SERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SERVER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = load_server()

    def test_valid_frame(self) -> None:
        stream = io.BytesIO(b"Content-Length: 2\r\n\r\n{}")
        self.assertEqual(self.server.read_message(stream), {})

    def test_missing_content_length(self) -> None:
        with self.assertRaises(self.server.LSPProtocolError):
            self.server.read_message(io.BytesIO(b"X-Test: 1\r\n\r\n{}"))

    def test_malformed_header(self) -> None:
        with self.assertRaises(self.server.LSPProtocolError):
            self.server.read_message(io.BytesIO(b"Broken\r\n\r\n"))

    def test_oversized_frame(self) -> None:
        length = self.server.MAX_MESSAGE_BYTES + 1
        with self.assertRaises(self.server.LSPProtocolError):
            self.server.read_message(
                io.BytesIO(f"Content-Length: {length}\r\n\r\n".encode("ascii"))
            )

    def test_short_body(self) -> None:
        with self.assertRaises(self.server.LSPProtocolError):
            self.server.read_message(io.BytesIO(b"Content-Length: 5\r\n\r\n{}"))

    def test_invalid_json(self) -> None:
        with self.assertRaises(self.server.LSPProtocolError):
            self.server.read_message(io.BytesIO(b"Content-Length: 1\r\n\r\n{"))

    def test_send_broken_pipe_returns_false(self) -> None:
        class BrokenStream:
            def write(self, _data):
                raise BrokenPipeError()

            def flush(self):
                pass

        self.assertFalse(self.server.send({"jsonrpc": "2.0"}, BrokenStream()))

    def test_post_shutdown_request_is_rejected(self) -> None:
        messages: list[dict] = []
        self.server.send = messages.append
        self.server.SHUTDOWN_REQUESTED = True
        keep_running = self.server.dispatch(
            {"jsonrpc": "2.0", "id": 9, "method": "textDocument/hover", "params": {}}
        )
        self.assertTrue(keep_running)
        self.assertEqual(messages[-1]["error"]["code"], -32600)

    def test_exit_after_shutdown_stops(self) -> None:
        self.server.SHUTDOWN_REQUESTED = True
        self.assertFalse(self.server.dispatch({"jsonrpc": "2.0", "method": "exit"}))


if __name__ == "__main__":
    unittest.main()
