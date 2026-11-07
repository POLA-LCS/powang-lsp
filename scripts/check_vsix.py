"""Inspect a packaged VSIX for stale vendored files and version drift."""

from __future__ import annotations

import glob
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STALE_FILES = [
    "extension/src/builtins/native_methods.py",
    "extension/src/stdlib_crypto.py",
    "extension/src/stdlib_env.py",
    "extension/src/stdlib_http.py",
    "extension/src/stdlib_http_router.py",
    "extension/src/stdlib_http_server.py",
    "extension/src/stdlib_json.py",
    "extension/src/stdlib_log.py",
    "extension/src/stdlib_strings.py",
    "extension/src/stdlib_time.py",
    "extension/src/stdlib_url.py",
]

REQUIRED_FILES = [
    "extension/package.json",
    "extension/server/powang_lsp.py",
    "extension/src/stdlib/stdlib_strings.py",
    "extension/src/builtins/native_methods/__init__.py",
]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_vsix.py <vsix path or glob>", file=sys.stderr)
        return 2
    matches = glob.glob(sys.argv[1])
    if not matches:
        print(f"vsix: no file matches {sys.argv[1]}", file=sys.stderr)
        return 1
    vsix = Path(matches[0])

    errors: list[str] = []
    with zipfile.ZipFile(vsix) as archive:
        names = set(archive.namelist())
        for stale in STALE_FILES:
            if stale in names:
                errors.append(f"stale file: {stale}")
        for required in REQUIRED_FILES:
            if required not in names:
                errors.append(f"missing: {required}")
        for name in names:
            if "__pycache__" in name or name.endswith(".pyc"):
                errors.append(f"bytecode file: {name}")
                break
        package = json.loads(archive.read("extension/package.json"))
        repo_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        if package["version"] != repo_package["version"]:
            errors.append(
                f"packaged {package['version']} != repo {repo_package['version']}"
            )

    if errors:
        print("vsix: invalid", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"vsix: ok ({vsix.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
