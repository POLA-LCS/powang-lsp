"""Fail when the vendored powang source tree drifts from its pinned commit."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def python_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reference",
        required=True,
        help="path to the pinned powang src directory",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    vendored_root = repo_root / "src"
    reference_root = Path(args.reference).resolve()

    if not vendored_root.is_dir():
        print(f"vendored src: missing {vendored_root}", file=sys.stderr)
        return 1
    if not reference_root.is_dir():
        print(f"vendored src: missing reference {reference_root}", file=sys.stderr)
        return 1

    vendored = python_files(vendored_root)
    reference = python_files(reference_root)

    errors: list[str] = []
    for name in sorted(reference.keys() - vendored.keys()):
        errors.append(f"missing: {name}")
    for name in sorted(vendored.keys() - reference.keys()):
        errors.append(f"extra: {name}")
    for name in sorted(reference.keys() & vendored.keys()):
        if digest(reference[name]) != digest(vendored[name]):
            errors.append(f"changed: {name}")

    if errors:
        print("vendored src: drift detected", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"vendored src: ok ({len(reference)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
