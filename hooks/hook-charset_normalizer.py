from __future__ import annotations

import importlib
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# launcher.py imports charset_normalizer during packaged smoke validation,
# so collect the whole package instead of relying on implicit analysis.
datas, binaries, hiddenimports = collect_all("charset_normalizer")


def _charset_normalizer_mypyc_hiddenimports() -> list[str]:
    """Collect charset_normalizer's companion mypyc modules when present.

    Recent Windows wheels ship a top-level hashed `*__mypyc.pyd` helper outside
    the package directory. PyInstaller does not discover that helper from the
    package name alone, so the packaged launcher needs to surface it explicitly.
    """

    try:
        package = importlib.import_module("charset_normalizer")
    except Exception:
        return []

    package_file = str(getattr(package, "__file__", "") or "").strip()
    if not package_file:
        return []
    try:
        site_root = Path(package_file).resolve().parent.parent
    except Exception:
        return []

    extras: list[str] = []
    for name, module in list(sys.modules.items()):
        if not str(name or "").endswith("__mypyc"):
            continue
        origin = str(getattr(module, "__file__", "") or "").strip()
        if not origin:
            continue
        try:
            if Path(origin).resolve().parent != site_root:
                continue
        except Exception:
            continue
        extras.append(str(name))
    return sorted(set(extras))


for _name in _charset_normalizer_mypyc_hiddenimports():
    if _name not in hiddenimports:
        hiddenimports.append(_name)
