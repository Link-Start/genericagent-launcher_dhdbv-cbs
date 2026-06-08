from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class BuildReleaseBundleTests(unittest.TestCase):
    def _make_dist_tree(self, root: str) -> str:
        dist_dir = os.path.join(root, "dist")
        app_dir = os.path.join(dist_dir, "GenericAgentLauncher")
        os.makedirs(app_dir, exist_ok=True)
        with open(os.path.join(app_dir, "launcher.txt"), "w", encoding="utf-8") as f:
            f.write("ok")
        with open(os.path.join(dist_dir, "LauncherBootstrap.exe"), "wb") as f:
            f.write(b"bootstrap")
        with open(os.path.join(dist_dir, "Updater.exe"), "wb") as f:
            f.write(b"updater")
        return dist_dir

    def test_allow_unsigned_build_skips_empty_manifest_sig(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with tempfile.TemporaryDirectory() as td:
            dist_dir = self._make_dist_tree(td)
            out_dir = os.path.join(td, "release")
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/build_release_bundle.py",
                    "--version",
                    "9.9.9-test",
                    "--dist",
                    dist_dir,
                    "--out",
                    out_dir,
                    "--allow-unsigned",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={k: v for k, v in os.environ.items() if not k.startswith("GA_LAUNCHER_UPDATE_")},
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            release_dir = os.path.join(out_dir, "9.9.9-test", "update")
            manifest_sig = os.path.join(release_dir, "manifest.sig")
            self.assertFalse(os.path.exists(manifest_sig), msg="unsigned local build should not leave manifest.sig behind")
            with open(os.path.join(release_dir, "sha256sums.txt"), "r", encoding="utf-8") as f:
                sums = f.read()
            self.assertNotIn("manifest.sig", sums)

    def test_signed_build_writes_non_empty_manifest_sig_and_public_key(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with tempfile.TemporaryDirectory() as td:
            dist_dir = self._make_dist_tree(td)
            out_dir = os.path.join(td, "release")
            private_key = Ed25519PrivateKey.generate()
            public_key = private_key.public_key()
            private_key_path = os.path.join(td, "update_signing_private_key.pem")
            public_key_path = os.path.join(td, "update_signing_public_key.pem")
            with open(private_key_path, "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )
            with open(public_key_path, "wb") as f:
                f.write(
                    public_key.public_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                )
            env = dict(os.environ)
            env["GA_LAUNCHER_UPDATE_PRIVATE_KEY_FILE"] = private_key_path
            env["GA_LAUNCHER_UPDATE_PUBLIC_KEY_FILE"] = public_key_path
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/build_release_bundle.py",
                    "--version",
                    "9.9.9-test",
                    "--dist",
                    dist_dir,
                    "--out",
                    out_dir,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            release_dir = os.path.join(out_dir, "9.9.9-test")
            manifest_sig = os.path.join(release_dir, "update", "manifest.sig")
            self.assertTrue(os.path.isfile(manifest_sig))
            self.assertGreater(os.path.getsize(manifest_sig), 0)
            with open(os.path.join(release_dir, "install", "update_public_key.pem"), "r", encoding="utf-8") as f:
                embedded_public = f.read().strip()
            with open(public_key_path, "r", encoding="utf-8") as f:
                expected_public = f.read().strip()
            self.assertEqual(embedded_public, expected_public)
            with open(os.path.join(release_dir, "install", "update_public_key.pem"), "rb") as f:
                embedded_public_bytes = f.read()
            with open(public_key_path, "rb") as f:
                expected_public_bytes = f.read()
            self.assertEqual(embedded_public_bytes, expected_public_bytes)
            for rel_path in (
                os.path.join("install", "update_public_key.pem"),
                os.path.join("update", "manifest.sig"),
                os.path.join("update", "sha256sums.txt"),
            ):
                with open(os.path.join(release_dir, rel_path), "rb") as f:
                    self.assertNotIn(b"\r\n", f.read())

    def test_release_build_without_private_key_fails(self):
        root = os.path.dirname(os.path.dirname(__file__))
        with tempfile.TemporaryDirectory() as td:
            dist_dir = self._make_dist_tree(td)
            out_dir = os.path.join(td, "release")
            result = subprocess.run(
                [
                    sys.executable,
                    "tools/build_release_bundle.py",
                    "--version",
                    "9.9.9-test",
                    "--dist",
                    dist_dir,
                    "--out",
                    out_dir,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={k: v for k, v in os.environ.items() if not k.startswith("GA_LAUNCHER_UPDATE_")},
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("update signing key is missing", result.stderr or result.stdout)
