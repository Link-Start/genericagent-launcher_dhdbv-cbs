from __future__ import annotations

import argparse
import os
import re
import sys


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[.+_-][0-9A-Za-z][0-9A-Za-z.+_-]*)?$")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _canonical_version_path(path: str = "") -> str:
    raw = str(path or "").strip()
    if raw:
        if os.path.isabs(raw):
            return os.path.abspath(raw)
        return os.path.abspath(os.path.join(_repo_root(), raw))
    return os.path.join(_repo_root(), "release", "VERSION")


def _normalize_version(value: str, *, source_label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SystemExit(f"{source_label} is empty")
    if text.startswith("v"):
        text = text[1:].strip()
    if not text:
        raise SystemExit(f"{source_label} is empty")
    if any(ch.isspace() for ch in text):
        raise SystemExit(f"{source_label} contains whitespace: {value!r}")
    if not VERSION_PATTERN.fullmatch(text):
        raise SystemExit(
            f"{source_label} is not a valid release version: {value!r}. "
            "Expected a semver-style string such as 0.2.0 or 0.2.0-rc1."
        )
    return text


def read_canonical_release_version(path: str = "") -> str:
    version_path = _canonical_version_path(path)
    if not os.path.isfile(version_path):
        raise SystemExit(f"canonical release version file is missing: {version_path}")
    try:
        with open(version_path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError as exc:
        raise SystemExit(f"failed to read canonical release version file {version_path}: {exc}") from exc
    return _normalize_version(raw, source_label=f"canonical release version file {version_path}")


def resolve_release_version(*, expected: str = "", expected_label: str = "", path: str = "") -> str:
    canonical = read_canonical_release_version(path)
    normalized_expected = str(expected or "").strip()
    if normalized_expected:
        normalized_expected = _normalize_version(
            normalized_expected,
            source_label=(expected_label or "expected release version"),
        )
        if normalized_expected != canonical:
            label = expected_label or "expected release version"
            raise SystemExit(
                f"release version mismatch: {label} resolved to {normalized_expected}, "
                f"but release/VERSION is {canonical}. Update release/VERSION first."
            )
    return canonical


def _parse_args():
    parser = argparse.ArgumentParser(description="Resolve the canonical GenericAgent Launcher release version")
    parser.add_argument(
        "--path",
        default="release/VERSION",
        help="Canonical release version file path, relative to repo root by default",
    )
    parser.add_argument(
        "--expected",
        default="",
        help="Optional release version from a tag, workflow input, or local argument; must match the canonical file",
    )
    parser.add_argument(
        "--expected-label",
        default="",
        help="Human-readable label used in mismatch errors",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    version = resolve_release_version(
        expected=str(args.expected or "").strip(),
        expected_label=str(args.expected_label or "").strip(),
        path=str(args.path or "").strip(),
    )
    sys.stdout.write(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
