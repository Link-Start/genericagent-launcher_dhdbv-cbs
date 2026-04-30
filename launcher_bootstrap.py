from __future__ import annotations

import os
import re
import sys

from launcher_core_parts.constants import MAIN_EXE_NAME
from launcher_core_parts.runtime import (
    _popen_external_subprocess,
    load_version_state,
    resolved_versions_dir,
    set_current_version,
)


def _normalized_existing_file(path: str) -> str:
    text = os.path.abspath(str(path or "").strip())
    if not text or (not os.path.isfile(text)):
        return ""
    return os.path.normcase(os.path.normpath(text))


def _self_executable_path() -> str:
    if not getattr(sys, "frozen", False):
        return ""
    return _normalized_existing_file(sys.executable)


def _version_sort_key(text: str):
    parts = []
    for chunk in re.split(r"[.+-]", str(text or "").strip().lower().lstrip("v")):
        if not chunk:
            continue
        if chunk.isdigit():
            parts.append((0, int(chunk)))
        else:
            parts.append((1, chunk))
    return tuple(parts)


def _pick_target_executable() -> str:
    self_exe = _self_executable_path()

    def _accept(path: str) -> str:
        resolved = _normalized_existing_file(path)
        if not resolved:
            return ""
        if self_exe and resolved == self_exe:
            return ""
        return resolved

    state = load_version_state()
    current = str((state or {}).get("current_version") or "").strip()
    if current:
        candidate = os.path.join(resolved_versions_dir(), current, MAIN_EXE_NAME)
        selected = _accept(candidate)
        if selected:
            return selected
    versions_dir = resolved_versions_dir()
    if os.path.isdir(versions_dir):
        candidates = []
        for name in os.listdir(versions_dir):
            fp = os.path.join(versions_dir, name, MAIN_EXE_NAME)
            selected = _accept(fp)
            if selected:
                candidates.append((name, selected))
        if candidates:
            candidates.sort(key=lambda item: _version_sort_key(item[0]), reverse=True)
            selected_version, selected_fp = candidates[0]
            try:
                set_current_version(selected_version, previous_version="", pending_update={})
            except Exception:
                pass
            return selected_fp
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    for fallback in (
        os.path.join(exe_dir, MAIN_EXE_NAME),
        os.path.join(exe_dir, os.path.splitext(MAIN_EXE_NAME)[0], MAIN_EXE_NAME),
    ):
        selected = _accept(fallback)
        if selected:
            return selected
    return ""


def _show_bootstrap_error(text: str) -> None:
    message = str(text or "").strip() or "启动失败。"
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "LauncherBootstrap", 0x10)
            return
    except Exception:
        pass
    sys.stderr.write(message + "\n")


def run() -> int:
    if not getattr(sys, "frozen", False):
        from launcher import run as main_run

        agent_dir = sys.argv[1] if len(sys.argv) > 1 else None
        return int(main_run(agent_dir))
    target = _pick_target_executable()
    if not target:
        _show_bootstrap_error("未找到可启动的 GenericAgentLauncher.exe。请重新安装启动器。")
        return 1
    args = [target, *sys.argv[1:]]
    try:
        _popen_external_subprocess(args, cwd=os.path.dirname(target))
        return 0
    except Exception as e:
        _show_bootstrap_error(f"启动失败：{e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
