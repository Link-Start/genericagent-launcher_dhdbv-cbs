# -*- mode: python ; coding: utf-8 -*-
import os


def _resolve_root_dir():
    spec_path = globals().get("__file__") or globals().get("SPEC")
    if spec_path:
        return os.path.dirname(os.path.abspath(spec_path))

    fallback_spec_path = os.path.abspath(os.path.join(os.getcwd(), "LauncherBootstrap.spec"))
    return os.path.dirname(fallback_spec_path)


ROOT_DIR = _resolve_root_dir()
BOOTSTRAP_SCRIPT = os.path.join(ROOT_DIR, "launcher_bootstrap.py")
HOOKS_DIR = os.path.join(ROOT_DIR, "hooks")
WINDOWS_ICON_PATH = os.path.join(ROOT_DIR, "assets", "launcher_app_icon.ico")

a = Analysis(
    [BOOTSTRAP_SCRIPT],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="LauncherBootstrap",
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
