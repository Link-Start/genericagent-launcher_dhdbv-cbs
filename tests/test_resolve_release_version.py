from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest


def _load_release_version_module():
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "tools", "resolve_release_version.py")
    spec = importlib.util.spec_from_file_location("resolve_release_version_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ResolveReleaseVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_release_version_module()

    def test_read_canonical_release_version_reads_release_version_file(self):
        with tempfile.TemporaryDirectory() as td:
            version_path = os.path.join(td, "VERSION")
            with open(version_path, "w", encoding="utf-8") as f:
                f.write("0.2.0\n")
            self.assertEqual(self.mod.read_canonical_release_version(version_path), "0.2.0")

    def test_resolve_release_version_accepts_matching_expected_value(self):
        with tempfile.TemporaryDirectory() as td:
            version_path = os.path.join(td, "VERSION")
            with open(version_path, "w", encoding="utf-8") as f:
                f.write("0.2.0\n")
            self.assertEqual(
                self.mod.resolve_release_version(
                    expected="v0.2.0",
                    expected_label="release trigger version",
                    path=version_path,
                ),
                "0.2.0",
            )

    def test_resolve_release_version_rejects_mismatched_expected_value(self):
        with tempfile.TemporaryDirectory() as td:
            version_path = os.path.join(td, "VERSION")
            with open(version_path, "w", encoding="utf-8") as f:
                f.write("0.2.0\n")
            with self.assertRaises(SystemExit) as ctx:
                self.mod.resolve_release_version(
                    expected="0.1.9",
                    expected_label="release trigger version",
                    path=version_path,
                )
        self.assertIn("release/VERSION is 0.2.0", str(ctx.exception))

    def test_read_canonical_release_version_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            missing = os.path.join(td, "VERSION")
            with self.assertRaises(SystemExit) as ctx:
                self.mod.read_canonical_release_version(missing)
        self.assertIn("canonical release version file is missing", str(ctx.exception))
