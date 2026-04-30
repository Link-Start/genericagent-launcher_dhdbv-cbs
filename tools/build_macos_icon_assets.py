from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

APP_ICONSET_NAME = "GenericAgentLauncher.iconset"
APP_ICNS_NAME = "GenericAgentLauncher.icns"
ICONSET_BASE_SIZES = (16, 32, 128, 256, 512)


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_icon_svg_path(root: str | None = None) -> str:
    resolved_root = os.path.abspath(root or repo_root())
    return os.path.join(resolved_root, "assets", "launcher_app_icon.svg")


def default_icon_build_dir(root: str | None = None) -> str:
    resolved_root = os.path.abspath(root or repo_root())
    return os.path.join(resolved_root, "build", "macos-icon")


def default_icns_output_path(root: str | None = None) -> str:
    return os.path.join(default_icon_build_dir(root), APP_ICNS_NAME)


def iconset_entries() -> tuple[tuple[str, int], ...]:
    return (
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    )


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(detail or f"command failed: {' '.join(cmd)}")
    return result


def _render_png(svg_path: str, png_path: str, size: int) -> str:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        raise SystemExit(f"invalid SVG icon asset: {svg_path}")

    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    if not image.save(png_path):
        raise SystemExit(f"failed to save PNG icon: {png_path}")
    return png_path


def build_iconset(svg_path: str | None = None, out_root: str | None = None) -> str:
    resolved_svg = os.path.abspath(svg_path or default_icon_svg_path())
    if not os.path.isfile(resolved_svg):
        raise SystemExit(f"icon SVG asset not found: {resolved_svg}")

    resolved_out_root = os.path.abspath(out_root or default_icon_build_dir())
    iconset_dir = os.path.join(resolved_out_root, APP_ICONSET_NAME)
    shutil.rmtree(iconset_dir, ignore_errors=True)
    os.makedirs(iconset_dir, exist_ok=True)
    for filename, size in iconset_entries():
        _render_png(resolved_svg, os.path.join(iconset_dir, filename), size)
    return iconset_dir


def build_icns(svg_path: str | None = None, icns_path: str | None = None) -> str:
    if sys.platform != "darwin":
        raise SystemExit("tools/build_macos_icon_assets.py must run on macOS")

    resolved_icns_path = os.path.abspath(icns_path or default_icns_output_path())
    os.makedirs(os.path.dirname(resolved_icns_path), exist_ok=True)
    iconset_dir = build_iconset(
        svg_path=svg_path or default_icon_svg_path(),
        out_root=os.path.dirname(resolved_icns_path),
    )
    if os.path.isfile(resolved_icns_path):
        os.remove(resolved_icns_path)
    _run(["iconutil", "-c", "icns", iconset_dir, "-o", resolved_icns_path])
    return resolved_icns_path


def _parse_args():
    parser = argparse.ArgumentParser(description="Build macOS .icns assets from the launcher SVG icon")
    parser.add_argument("--svg", default="", help="Override source SVG path")
    parser.add_argument("--out", default="", help="Override output .icns path")
    return parser.parse_args()


def main() -> int:
    if sys.platform != "darwin":
        raise SystemExit("tools/build_macos_icon_assets.py must run on macOS")

    args = _parse_args()
    icns_path = build_icns(
        svg_path=str(args.svg or "").strip() or None,
        icns_path=str(args.out or "").strip() or None,
    )
    print(f"macOS app icon ready: {icns_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
