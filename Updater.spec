# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all


def _resolve_root_dir():
    spec_path = globals().get("__file__") or globals().get("SPEC")
    if spec_path:
        return os.path.dirname(os.path.abspath(spec_path))

    fallback_spec_path = os.path.abspath(os.path.join(os.getcwd(), "Updater.spec"))
    return os.path.dirname(fallback_spec_path)


ROOT_DIR = _resolve_root_dir()
UPDATER_SCRIPT = os.path.join(ROOT_DIR, "updater.py")
HOOKS_DIR = os.path.join(ROOT_DIR, "hooks")
WINDOWS_ICON_PATH = os.path.join(ROOT_DIR, "assets", "launcher_app_icon.ico")

binaries = []
datas = []
hiddenimports = []
for _package in ("requests", "simplejson", "charset_normalizer", "cryptography"):
    _package_datas, _package_binaries, _package_hiddenimports = collect_all(_package)
    datas += _package_datas
    binaries += _package_binaries
    hiddenimports += _package_hiddenimports

a = Analysis(
    [UPDATER_SCRIPT],
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
    a.binaries,
    a.datas,
    [],
    name="Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=WINDOWS_ICON_PATH if os.path.isfile(WINDOWS_ICON_PATH) else None,
)
