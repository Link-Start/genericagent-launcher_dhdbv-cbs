from __future__ import annotations

import os
import sys

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

_ICON_CACHE: dict[int, QIcon] = {}
_SVG_CACHE = ""
_FALLBACK_ICON_SVG = """
<svg width="256" height="256" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="24" y="24" width="208" height="208" rx="52" fill="#08111F"/>
  <rect x="36" y="36" width="184" height="184" rx="42" fill="url(#panel)"/>
  <path d="M88 170V112C88 87.6995 107.699 68 132 68H138C162.301 68 182 87.6995 182 112V138C182 162.301 162.301 182 138 182H88" stroke="url(#gate)" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M110 174C142 172 165 160 182 138" stroke="#67E8F9" stroke-width="14" stroke-linecap="round"/>
  <path d="M166 138L196 138L196 108" stroke="#22D3EE" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <defs>
    <linearGradient id="panel" x1="36" y1="36" x2="220" y2="220" gradientUnits="userSpaceOnUse">
      <stop stop-color="#0B1730"/>
      <stop offset="1" stop-color="#0E223E"/>
    </linearGradient>
    <linearGradient id="gate" x1="88" y1="68" x2="188" y2="182" gradientUnits="userSpaceOnUse">
      <stop stop-color="#93C5FD"/>
      <stop offset="1" stop-color="#22D3EE"/>
    </linearGradient>
  </defs>
</svg>
""".strip()


def _icon_asset_candidates() -> list[str]:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(base, "assets", "launcher_app_icon.svg"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "assets", "launcher_app_icon.svg"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "..", "Resources", "assets", "launcher_app_icon.svg"),
    ]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.insert(0, os.path.join(str(meipass), "assets", "launcher_app_icon.svg"))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.normpath(str(candidate)))
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(os.path.abspath(candidate))
    return deduped


def _icon_asset_path() -> str:
    for candidate in _icon_asset_candidates():
        if os.path.isfile(candidate):
            return candidate
    return _icon_asset_candidates()[0]


def launcher_icon_svg() -> str:
    global _SVG_CACHE
    if _SVG_CACHE:
        return _SVG_CACHE
    for path in _icon_asset_candidates():
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            _SVG_CACHE = f.read().strip()
        if _SVG_CACHE:
            return _SVG_CACHE
    _SVG_CACHE = _FALLBACK_ICON_SVG
    return _SVG_CACHE


def launcher_icon(size: int = 256) -> QIcon:
    icon_size = max(32, int(size or 256))
    cached = _ICON_CACHE.get(icon_size)
    if cached is not None:
        return cached

    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(launcher_icon_svg().encode("utf-8")))
    pixmap = QPixmap(icon_size, icon_size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QIcon(pixmap)
    _ICON_CACHE[icon_size] = icon
    return icon
