"""Check that the extension, server and changelog versions agree."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    version = package["version"]

    server_text = (ROOT / "server" / "powang_lsp.py").read_text(encoding="utf-8")
    match = re.search(
        r'"serverInfo"\s*:\s*\{[^}]*"version"\s*:\s*"([^"]+)"',
        server_text,
        re.DOTALL,
    )
    if match is None:
        print("versions: serverInfo.version not found", file=sys.stderr)
        return 1
    server_version = match.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = re.findall(r"^##\s+(\S+)", changelog, re.MULTILINE)
    versions = [heading for heading in headings if heading != "Unreleased"]

    errors: list[str] = []
    if server_version != version:
        errors.append(f"server {server_version} != package {version}")
    if not versions:
        errors.append("CHANGELOG has no version heading")
    elif versions[0] != version:
        errors.append(f"CHANGELOG {versions[0]} != package {version}")

    if errors:
        print("versions: mismatch", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"versions: ok ({version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
