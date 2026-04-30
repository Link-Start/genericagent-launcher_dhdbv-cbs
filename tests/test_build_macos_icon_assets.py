from __future__ import annotations

import importlib.util
import os
import unittest


def _load_build_macos_icon_assets_module():
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "tools", "build_macos_icon_assets.py")
    spec = importlib.util.spec_from_file_location("build_macos_icon_assets_module", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BuildMacOSIconAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_build_macos_icon_assets_module()

    def test_iconset_entries_cover_required_icns_sizes(self):
        entries = dict(self.mod.iconset_entries())
        self.assertEqual(entries["icon_16x16.png"], 16)
        self.assertEqual(entries["icon_16x16@2x.png"], 32)
        self.assertEqual(entries["icon_32x32.png"], 32)
        self.assertEqual(entries["icon_32x32@2x.png"], 64)
        self.assertEqual(entries["icon_128x128.png"], 128)
        self.assertEqual(entries["icon_128x128@2x.png"], 256)
        self.assertEqual(entries["icon_256x256.png"], 256)
        self.assertEqual(entries["icon_256x256@2x.png"], 512)
        self.assertEqual(entries["icon_512x512.png"], 512)
        self.assertEqual(entries["icon_512x512@2x.png"], 1024)

    def test_default_paths_point_to_repo_assets_and_build_output(self):
        root = os.path.dirname(os.path.dirname(__file__))
        self.assertEqual(
            self.mod.default_icon_svg_path(root),
            os.path.join(root, "assets", "launcher_app_icon.svg"),
        )
        self.assertEqual(
            self.mod.default_icns_output_path(root),
            os.path.join(root, "build", "macos-icon", "GenericAgentLauncher.icns"),
        )


if __name__ == "__main__":
    unittest.main()
