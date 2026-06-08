# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files


def _resolve_root_dir():
    spec_path = globals().get("__file__") or globals().get("SPEC")
    if spec_path:
        return os.path.dirname(os.path.abspath(spec_path))

    fallback_spec_path = os.path.abspath(os.path.join(os.getcwd(), "GenericAgentLauncher.spec"))
    return os.path.dirname(fallback_spec_path)


ROOT_DIR = _resolve_root_dir()
LAUNCHER_SCRIPT = os.path.join(ROOT_DIR, "launcher.py")
BRIDGE_PATH = os.path.join(ROOT_DIR, "bridge.py")
HOOKS_DIR = os.path.join(ROOT_DIR, "hooks")
APP_ICON_SVG_PATH = os.path.join(ROOT_DIR, "assets", "launcher_app_icon.svg")
WINDOWS_ICON_PATH = os.path.join(ROOT_DIR, "assets", "launcher_app_icon.ico")

datas = [(BRIDGE_PATH, "."), (APP_ICON_SVG_PATH, "assets")]
hiddenimports = [
    "launcher_app.window",
    "shiboken6",
    "requests",
    "simplejson",
    "charset_normalizer",
    "cryptography",
]
binaries = []
for _package in ("requests", "simplejson", "charset_normalizer", "cryptography"):
    _package_datas, _package_binaries, _package_hiddenimports = collect_all(_package)
    datas += _package_datas
    binaries += _package_binaries
    hiddenimports += _package_hiddenimports

hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
]
datas += collect_data_files("PySide6", subdir="plugins/platforms")
datas += collect_data_files("PySide6", subdir="plugins/styles")
datas += collect_data_files("PySide6", subdir="plugins/imageformats")

a = Analysis(
    [LAUNCHER_SCRIPT],
    pathex=[ROOT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[HOOKS_DIR],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GenericAgentLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=WINDOWS_ICON_PATH if os.path.isfile(WINDOWS_ICON_PATH) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GenericAgentLauncher",
)
