from __future__ import annotations

import json
import os
import threading
import time
import uuid
import urllib.error
import urllib.request

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from launcher_app import core as lz
from launcher_app.theme import C, F

from . import common as chat_common
from .common import InputTextEdit, MessageRow, build_message_row


class ConductorPageMixin:
    """Conductor workspace:
    left = session management
    right = upstream-style dual panel (subagent cards + conductor chat)
    """

    def _conductor_ui_alive(self) -> bool:
        if bool(getattr(self, "_closing_in_progress", False) or getattr(self, "_force_exit_requested", False) or getattr(self, "_app_quit_requested", False)):
            return False
        checker = getattr(self, "_qt_object_alive", None)
        if callable(checker):
            try:
                if not checker(self):
                    return False
            except Exception:
                return False
        app = QApplication.instance()
        if app is None:
            return False
        if callable(checker):
            try:
                return bool(checker(app))
            except Exception:
                return False
        return True

    def _conductor_post_ui(self, fn):
        """Post a callback to the UI thread only if the app is still alive.

        Avoids: QObject::startTimer: current thread's event dispatcher has already been destroyed
        when background Conductor threads finish after shutdown.
        """
        callback = fn if callable(fn) else (lambda: None)
        if not self._conductor_ui_alive():
            return
        poster = getattr(self, "_api_on_ui_thread", None)
        if callable(poster):
            try:
                poster(callback)
                return
            except Exception:
                return
        # No shared poster: refuse to create timers from non-UI threads after quit.
        return

    def _build_conductor_page(self) -> QWidget:
        from launcher_app import theme as qt_theme

        chat_bg = qt_theme.chat_surface_background()
        body_fs = qt_theme.font_body_size()

        page = QWidget()
        page.setObjectName("conductorPage")
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── left: session management ───────────────────────────────────
        sidebar = QFrame()
        sidebar.setObjectName("chatSidebar")
        sidebar.setFixedWidth(280)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 14, 14, 14)
        side.setSpacing(8)

        brand = QLabel("Conductor")
        brand.setObjectName("cardTitle")
        side.addWidget(brand)

        new_btn = QPushButton("新会话")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.setStyleSheet(self._sidebar_button_style(primary=True))
        new_btn.clicked.connect(self._conductor_new_session)
        chat_common.set_button_svg_icon(new_btn, "conductor_new", chat_common._SVG_PLUS, color="accent_text", size=16)
        side.addWidget(new_btn)

        refresh_btn = QPushButton("刷新会话")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet(self._sidebar_button_style(subtle=True))
        refresh_btn.clicked.connect(self._conductor_refresh_all)
        chat_common.set_button_svg_icon(refresh_btn, "conductor_refresh", chat_common._SVG_REFRESH, color="text_soft", size=16)
        side.addWidget(refresh_btn)

        group = QLabel("会话")
        group.setObjectName("sectionLabel")
        side.addWidget(group)

        self.conductor_session_list = QListWidget()
        self.conductor_session_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.conductor_session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.conductor_session_list.currentItemChanged.connect(self._on_conductor_session_item_changed)
        self.conductor_session_list.customContextMenuRequested.connect(self._open_conductor_session_context_menu)
        side.addWidget(self.conductor_session_list, 1)

        # Runtime is infrastructure, not part of the chat surface.
        runtime_box = QFrame()
        runtime_box.setStyleSheet("background: transparent;")
        runtime_col = QVBoxLayout(runtime_box)
        runtime_col.setContentsMargins(0, 8, 0, 0)
        runtime_col.setSpacing(6)
        runtime_label = QLabel("后台服务")
        runtime_label.setObjectName("sectionLabel")
        runtime_col.addWidget(runtime_label)
        self.conductor_status_label = QLabel("未启动")
        self.conductor_status_label.setObjectName("mutedText")
        self.conductor_status_label.setWordWrap(True)
        runtime_col.addWidget(self.conductor_status_label)
        self.conductor_runtime_btn = QPushButton("启动后台")
        self.conductor_runtime_btn.setCursor(Qt.PointingHandCursor)
        self.conductor_runtime_btn.setStyleSheet(self._sidebar_button_style(subtle=True))
        self.conductor_runtime_btn.clicked.connect(self._conductor_toggle_runtime)
        runtime_col.addWidget(self.conductor_runtime_btn)
        side.addWidget(runtime_box)
        root.addWidget(sidebar, 0)

        # ── right: upstream dual pane ──────────────────────────────────
        right_split = QSplitter(Qt.Horizontal)
        right_split.setHandleWidth(1)
        right_split.setChildrenCollapsible(False)

        # left-of-right: subagent cards
        sub_panel = QFrame()
        sub_panel.setObjectName("chatSidebar")
        sub_panel.setMinimumWidth(280)
        sub_col = QVBoxLayout(sub_panel)
        sub_col.setContentsMargins(0, 0, 0, 0)
        sub_col.setSpacing(0)
        sub_head = QFrame()
        sub_head.setObjectName("chatHead")
        sub_head.setFixedHeight(F["topbar_h"])
        sub_head_row = QHBoxLayout(sub_head)
        sub_head_row.setContentsMargins(16, 0, 16, 0)
        sub_title = QLabel("子 Agent")
        sub_title.setObjectName("cardTitle")
        sub_head_row.addWidget(sub_title, 0, Qt.AlignVCenter)
        sub_head_row.addStretch(1)
        self.conductor_side_hint = QLabel("0 个任务")
        self.conductor_side_hint.setObjectName("mutedText")
        sub_head_row.addWidget(self.conductor_side_hint, 0, Qt.AlignRight | Qt.AlignVCenter)
        sub_col.addWidget(sub_head)

        self.conductor_cards_scroll = QScrollArea()
        self.conductor_cards_scroll.setWidgetResizable(True)
        self.conductor_cards_scroll.setFrameShape(QFrame.NoFrame)
        self.conductor_cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conductor_cards_scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {chat_bg}; }}")
        self.conductor_cards_host = QWidget()
        self.conductor_cards_host.setStyleSheet(f"background: {chat_bg};")
        self.conductor_cards_layout = QVBoxLayout(self.conductor_cards_host)
        self.conductor_cards_layout.setContentsMargins(12, 12, 12, 12)
        self.conductor_cards_layout.setSpacing(10)
        self.conductor_cards_layout.addStretch(1)
        self.conductor_cards_scroll.setWidget(self.conductor_cards_host)
        sub_col.addWidget(self.conductor_cards_scroll, 1)
        right_split.addWidget(sub_panel)

        # right-of-right: conductor chat
        chat_panel = QFrame()
        chat_panel.setObjectName("chatMain")
        chat_col = QVBoxLayout(chat_panel)
        chat_col.setContentsMargins(0, 0, 0, 0)
        chat_col.setSpacing(0)

        chat_head = QFrame()
        chat_head.setObjectName("chatHead")
        chat_head.setFixedHeight(F["topbar_h"])
        chat_head_row = QHBoxLayout(chat_head)
        chat_head_row.setContentsMargins(18, 0, 18, 0)
        self.conductor_chat_title = QLabel("Conductor")
        self.conductor_chat_title.setObjectName("cardTitle")
        chat_head_row.addWidget(self.conductor_chat_title, 0, Qt.AlignVCenter)
        chat_head_row.addStretch(1)
        # Connection status only — no start/stop controls in the chat surface.
        self.conductor_conn_hint = QLabel("")
        self.conductor_conn_hint.setObjectName("mutedText")
        chat_head_row.addWidget(self.conductor_conn_hint, 0, Qt.AlignRight | Qt.AlignVCenter)
        chat_col.addWidget(chat_head)

        self.conductor_scroll = QScrollArea()
        self.conductor_scroll.setObjectName("chatScroll")
        self.conductor_scroll.setWidgetResizable(True)
        self.conductor_scroll.setFrameShape(QFrame.NoFrame)
        self.conductor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.conductor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Reuse main chat scrollbar styling when available.
        try:
            from launcher_app.window import SCROLLBAR_STYLE
        except Exception:
            SCROLLBAR_STYLE = ""
        self.conductor_scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {chat_bg}; }}" + SCROLLBAR_STYLE)
        vp = self.conductor_scroll.viewport()
        if vp is not None:
            vp.setStyleSheet(f"background: {chat_bg};")
        self.conductor_scroll.verticalScrollBar().valueChanged.connect(self._conductor_on_scroll_changed)
        self.conductor_msg_root = QWidget()
        self.conductor_msg_root.setObjectName("chatMsgRoot")
        self.conductor_msg_root.setStyleSheet(f"background: {chat_bg};")
        self.conductor_msg_layout = QVBoxLayout(self.conductor_msg_root)
        self.conductor_msg_layout.setContentsMargins(0, 12, 0, 12)
        self.conductor_msg_layout.setSpacing(4)
        self.conductor_msg_layout.setAlignment(Qt.AlignTop)
        self.conductor_msg_layout.addStretch(1)
        self.conductor_scroll.setWidget(self.conductor_msg_root)
        chat_col.addWidget(self.conductor_scroll, 1)

        self.conductor_jump_latest_btn = QPushButton(self.conductor_scroll.viewport())
        self.conductor_jump_latest_btn.setObjectName("jumpLatestBtn")
        self.conductor_jump_latest_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.conductor_jump_latest_btn.setToolTip("跳到最新对话")
        self.conductor_jump_latest_btn.setFixedSize(36, 36)
        jumper_style = getattr(self, "_jump_latest_button_style", None)
        if callable(jumper_style):
            self.conductor_jump_latest_btn.setStyleSheet(jumper_style())
        chat_common.set_button_svg_icon(
            self.conductor_jump_latest_btn,
            "conductor_jump_latest",
            chat_common._SVG_CHEVRON_DOWN,
            color="text",
            size=16,
        )
        self.conductor_jump_latest_btn.clicked.connect(self._conductor_jump_to_latest)
        self.conductor_jump_latest_btn.hide()

        footer = QFrame()
        footer.setObjectName("chatMain")
        footer_col = QVBoxLayout(footer)
        footer_col.setContentsMargins(16, 10, 16, 14)
        composer = QFrame()
        composer.setObjectName("chatComposer")
        composer_col = QVBoxLayout(composer)
        composer_col.setContentsMargins(12, 10, 12, 8)
        composer_col.setSpacing(8)
        self.conductor_input = InputTextEdit(self._conductor_handle_send)
        self.conductor_input.setPlaceholderText("直接给总管发消息，总管会调度子 Agent。Enter 发送，Shift+Enter 换行")
        self.conductor_input.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: none; color: {C['text']}; font-size: {body_fs}px; padding: 2px; }}"
        )
        self.conductor_input.setMinimumHeight(56)
        self.conductor_input.setMaximumHeight(120)
        # Reuse main chat slash-command wiring when present.
        configure = getattr(self, "_configure_chat_input_editor", None)
        if callable(configure):
            try:
                configure(self.conductor_input)
            except Exception:
                pass
        composer_col.addWidget(self.conductor_input)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addStretch(1)
        self.conductor_stop_btn = QPushButton("  中断")
        self.conductor_stop_btn.setObjectName("stopBtn")
        chat_common.set_button_svg_icon(
            self.conductor_stop_btn, "conductor_stop", chat_common._SVG_STOP, color="danger_text", size=14
        )
        self.conductor_stop_btn.setEnabled(False)
        self.conductor_stop_btn.setToolTip("停止 Conductor 后台任务（中断当前总管处理）")
        self.conductor_stop_btn.clicked.connect(self._conductor_abort_current)
        tools.addWidget(self.conductor_stop_btn)
        self.conductor_send_btn = QPushButton("  发送")
        self.conductor_send_btn.setObjectName("sendBtn")
        chat_common.set_button_svg_icon(self.conductor_send_btn, "conductor_send", chat_common._SVG_SEND, color="#ffffff", size=14)
        self.conductor_send_btn.clicked.connect(self._conductor_handle_send)
        tools.addWidget(self.conductor_send_btn)
        composer_col.addLayout(tools)
        footer_col.addWidget(composer)
        chat_col.addWidget(footer)
        self._conductor_user_scrolled_up = False
        self._conductor_busy = False

        right_split.addWidget(chat_panel)
        right_split.setStretchFactor(0, 0)
        right_split.setStretchFactor(1, 1)
        right_split.setSizes([360, 820])
        root.addWidget(right_split, 1)

        self._conductor_current_session = None
        self._conductor_rendered_message_rows = []
        self._conductor_chat_sig = ""
        self._conductor_sub_sig = ""
        self._conductor_poll_inflight = False
        self._conductor_card_widgets = []
        self._conductor_status_timer = QTimer(self)
        # Fast when streaming master output; relax when idle.
        self._conductor_status_timer.setInterval(400)
        self._conductor_status_timer.timeout.connect(self._conductor_poll_tick)
        self._conductor_stream_seq = 0
        self._conductor_reset_messages("给总管发消息即可调度子 Agent。")
        self._conductor_render_cards([])
        return page

    # ── HTTP ────────────────────────────────────────────────────────────
    def _conductor_base_url(self) -> str:
        getter = getattr(self, "_channel_web_url", None)
        if callable(getter):
            try:
                url = str(getter("conductor") or "").strip()
                if url:
                    return url.rstrip("/")
            except Exception:
                pass
        return "http://127.0.0.1:8900"

    def _conductor_http_json(self, method: str, path: str, payload=None, *, timeout=4.0):
        url = self._conductor_base_url() + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=str(method or "GET").upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return True, {}
            return True, json.loads(raw)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = str(e)
            return False, {"error": detail or str(e)}
        except Exception as e:
            return False, {"error": str(e)}

    def _conductor_proc_alive_quick(self) -> bool:
        """Local process check only — never blocks on HTTP."""
        alive = getattr(self, "_channel_proc_alive", None)
        if callable(alive):
            try:
                return bool(alive("conductor"))
            except Exception:
                return False
        return False

    def _conductor_is_running(self, *, allow_http: bool = False) -> bool:
        if self._conductor_proc_alive_quick():
            return True
        if not allow_http:
            return False
        ok, payload = self._conductor_http_json("GET", "/health", timeout=0.6)
        return bool(ok and isinstance(payload, dict) and (payload.get("ok") or payload.get("conductor_started")))

    def _conductor_set_starting_ui(self, starting: bool, *, detail: str = ""):
        self._conductor_start_inflight = bool(starting)
        if hasattr(self, "conductor_status_label") and self.conductor_status_label is not None:
            if starting:
                self.conductor_status_label.setText(detail or "后台启动中…")
            else:
                self._apply_conductor_runtime_status(self._conductor_proc_alive_quick())
        if hasattr(self, "conductor_runtime_btn") and self.conductor_runtime_btn is not None:
            self.conductor_runtime_btn.setEnabled(not starting)
            if starting:
                self.conductor_runtime_btn.setText("启动中…")
        if hasattr(self, "conductor_conn_hint") and self.conductor_conn_hint is not None:
            self.conductor_conn_hint.setText("连接中…" if starting else ("" if self._conductor_proc_alive_quick() else "后台未就绪"))
        send_btn = getattr(self, "conductor_send_btn", None)
        if send_btn is not None and starting:
            send_btn.setEnabled(True)  # still allow queueing sends

    def _conductor_ensure_runtime(self, *, show_errors=True, blocking=False, on_ready=None) -> bool:
        """Start Conductor off the UI thread by default.

        blocking=True only for rare callers that must wait (prefer async).
        Returns True immediately if already running / start already in flight.
        """
        if self._conductor_proc_alive_quick():
            if callable(on_ready):
                try:
                    on_ready(True, "")
                except Exception:
                    pass
            return True
        if bool(getattr(self, "_conductor_start_inflight", False)):
            if callable(on_ready):
                bucket = getattr(self, "_conductor_ready_callbacks", None)
                if not isinstance(bucket, list):
                    bucket = []
                    self._conductor_ready_callbacks = bucket
                bucket.append(on_ready)
            return False

        starter = getattr(self, "_start_channel_process", None)
        if not callable(starter):
            if callable(on_ready):
                try:
                    on_ready(False, "无法启动 Conductor。")
                except Exception:
                    pass
            return False

        if callable(on_ready):
            bucket = getattr(self, "_conductor_ready_callbacks", None)
            if not isinstance(bucket, list):
                bucket = []
                self._conductor_ready_callbacks = bucket
            bucket.append(on_ready)

        self._conductor_set_starting_ui(True, detail="后台启动中…")

        def worker():
            old = os.environ.get("GA_LAUNCHER_CONDUCTOR_NO_BROWSER")
            os.environ["GA_LAUNCHER_CONDUCTOR_NO_BROWSER"] = "1"
            ok = False
            err = ""
            try:
                ok = bool(starter("conductor", show_errors=False, force_local=True))
                if ok:
                    for _ in range(40):
                        if self._conductor_is_running(allow_http=True):
                            break
                        time.sleep(0.15)
                    else:
                        ok = self._conductor_is_running(allow_http=True)
                        if not ok:
                            err = "服务已拉起但健康检查超时。"
                else:
                    err = "启动 Conductor 失败，请检查 API 配置与依赖。"
            except Exception as e:
                ok = False
                err = str(e or "启动失败").strip() or "启动失败"
            finally:
                if old is None:
                    os.environ.pop("GA_LAUNCHER_CONDUCTOR_NO_BROWSER", None)
                else:
                    os.environ["GA_LAUNCHER_CONDUCTOR_NO_BROWSER"] = old

            def done():
                self._conductor_start_inflight = False
                self._apply_conductor_runtime_status(bool(ok and self._conductor_is_running(allow_http=False)) or self._conductor_proc_alive_quick())
                if hasattr(self, "conductor_runtime_btn") and self.conductor_runtime_btn is not None:
                    self.conductor_runtime_btn.setEnabled(True)
                if (not ok) and show_errors and err:
                    try:
                        QMessageBox.warning(self, "Conductor 未就绪", err)
                    except Exception:
                        pass
                callbacks = list(getattr(self, "_conductor_ready_callbacks", None) or [])
                self._conductor_ready_callbacks = []
                for cb in callbacks:
                    try:
                        cb(bool(ok), err)
                    except Exception:
                        pass
                if ok:
                    try:
                        self._conductor_pull_remote_chat()
                        self._conductor_pull_subagents()
                    except Exception:
                        pass

            self._conductor_post_ui(done)

        if blocking:
            worker()
            return self._conductor_proc_alive_quick() or self._conductor_is_running(allow_http=True)

        threading.Thread(target=worker, name="conductor-start", daemon=True).start()
        return False

    # ── sessions (left) ─────────────────────────────────────────────────
    def _conductor_session_rows(self):
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not (agent_dir and lz.is_valid_agent_dir(agent_dir)):
            return []
        rows = []
        try:
            for meta in lz.list_sessions(agent_dir) or []:
                if not isinstance(meta, dict):
                    continue
                if str(meta.get("channel_id") or "").strip().lower() == "conductor":
                    rows.append(meta)
        except Exception:
            rows = []
        rows.sort(key=lambda r: (0 if r.get("pinned") else 1, -float(r.get("updated_at", 0) or 0)))
        return rows

    def _refresh_conductor_sessions(self):
        lst = getattr(self, "conductor_session_list", None)
        if lst is None:
            return
        wanted = str(((self._conductor_current_session or {}).get("id") or "")).strip()
        selected_ids = set()
        for item in lst.selectedItems():
            sid = str(item.data(Qt.UserRole) or "").strip()
            if sid:
                selected_ids.add(sid)
        lst.blockSignals(True)
        lst.clear()
        rows = self._conductor_session_rows()
        if not rows:
            empty = QListWidgetItem("还没有会话\n点「新会话」开始")
            empty.setFlags(Qt.NoItemFlags)
            lst.addItem(empty)
        current_item = None
        for row in rows:
            sid = str(row.get("id") or "").strip()
            title = str(row.get("title") or sid or "新会话").strip() or "新会话"
            if bool(row.get("pinned", False)):
                title = f"★ {title}"
            when = ""
            try:
                when = time.strftime("%m-%d %H:%M", time.localtime(float(row.get("updated_at", 0) or 0)))
            except Exception:
                when = ""
            item = QListWidgetItem(f"{title}\n{when}" if when else title)
            item.setData(Qt.UserRole, {"id": sid, "title": row.get("title"), "pinned": bool(row.get("pinned", False))})
            item.setToolTip(f"{title}\n{when}" if when else title)
            lst.addItem(item)
            if wanted and sid == wanted:
                current_item = item
            if sid in selected_ids:
                item.setSelected(True)
        if current_item is not None:
            lst.setCurrentItem(current_item)
        lst.blockSignals(False)

    def _conductor_selected_session_rows(self):
        lst = getattr(self, "conductor_session_list", None)
        if lst is None:
            return []
        rows = []
        for item in lst.selectedItems():
            data = item.data(Qt.UserRole)
            if isinstance(data, dict) and str(data.get("id") or "").strip():
                rows.append(data)
            elif isinstance(data, str) and data.strip():
                rows.append({"id": data.strip()})
        return rows

    def _open_conductor_session_context_menu(self, pos):
        lst = getattr(self, "conductor_session_list", None)
        if lst is None:
            return
        item = lst.itemAt(pos)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not isinstance(data, (dict, str)):
            return
        if isinstance(data, str):
            data = {"id": data}
        if not str(data.get("id") or "").strip():
            return
        if not item.isSelected():
            lst.clearSelection()
            item.setSelected(True)
        rows = self._conductor_selected_session_rows()
        if not rows:
            return
        count = len(rows)
        all_pinned = all(bool(row.get("pinned", False)) for row in rows)
        menu = QMenu(self)
        chat_common.apply_menu_popup_theme(menu)
        rename_action = menu.addAction("重命名") if count == 1 else None
        pin_action = menu.addAction(f"{'取消收藏' if all_pinned else '收藏'}所选 ({count})")
        delete_action = menu.addAction(f"删除所选 ({count})")
        chosen = menu.exec(lst.viewport().mapToGlobal(pos))
        if chosen is rename_action:
            self._rename_conductor_session(rows[0])
            return
        if chosen is pin_action:
            self._set_conductor_sessions_pinned(rows, not all_pinned)
            return
        if chosen is delete_action:
            self._delete_conductor_sessions(rows)

    def _rename_conductor_session(self, row):
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        sid = str((row or {}).get("id") or "").strip()
        if not agent_dir or not sid:
            return
        try:
            data = lz.load_session(agent_dir, sid)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        old_title = str(data.get("title") or "").strip()
        text, ok = QInputDialog.getText(self, "重命名会话", "会话名称", text=old_title)
        if not ok:
            return
        new_title = str(text or "").strip()
        if not new_title or new_title == old_title:
            return
        data["title"] = new_title
        try:
            lz.save_session(agent_dir, data, touch=True)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e or "保存会话失败。"))
            return
        if str(((self._conductor_current_session or {}).get("id") or "")) == sid:
            self._conductor_current_session = dict(self._conductor_current_session or {})
            self._conductor_current_session["title"] = new_title
            if hasattr(self, "conductor_chat_title"):
                self.conductor_chat_title.setText(new_title)
        self._refresh_conductor_sessions()

    def _set_conductor_sessions_pinned(self, rows, pinned: bool):
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not agent_dir:
            return
        failed = []
        for row in rows:
            sid = str((row or {}).get("id") or "").strip()
            if not sid:
                continue
            try:
                data = lz.load_session(agent_dir, sid)
            except Exception:
                data = None
            if not isinstance(data, dict):
                continue
            data["pinned"] = bool(pinned)
            try:
                lz.save_session(agent_dir, data, touch=True)
            except Exception as e:
                failed.append(str(e or "保存失败"))
            if str(((self._conductor_current_session or {}).get("id") or "")) == sid:
                self._conductor_current_session = dict(self._conductor_current_session or {})
                self._conductor_current_session["pinned"] = bool(pinned)
        self._refresh_conductor_sessions()
        if failed:
            QMessageBox.warning(self, "保存失败", "\n".join(dict.fromkeys(failed)))

    def _delete_conductor_sessions(self, rows):
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not agent_dir or not rows:
            return
        count = len(rows)
        if QMessageBox.question(self, "删除会话", f"确定删除选中的 {count} 个 Conductor 会话？") != QMessageBox.Yes:
            return
        current_sid = str(((self._conductor_current_session or {}).get("id") or ""))
        deleted_current = False
        for row in rows:
            sid = str((row or {}).get("id") or "").strip()
            if not sid:
                continue
            try:
                lz.delete_session(agent_dir, sid)
            except Exception:
                continue
            if sid == current_sid:
                deleted_current = True
        if deleted_current:
            self._conductor_current_session = None
            self._conductor_reset_messages("会话已删除。点「新会话」或选择其它会话。")
            if hasattr(self, "conductor_chat_title"):
                self.conductor_chat_title.setText("Conductor")
        self._refresh_conductor_sessions()

    def _conductor_new_session(self, *, start_runtime: bool = True):
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not (agent_dir and lz.is_valid_agent_dir(agent_dir)):
            return
        sid = uuid.uuid4().hex[:12]
        session = {
            "id": sid,
            "title": "Conductor 会话",
            "created_at": time.time(),
            "updated_at": time.time(),
            "bubbles": [],
            "pinned": False,
            "channel_id": "conductor",
            "channel_label": lz._usage_channel_label("conductor"),
            "session_source_label": "Conductor",
            "session_kind": "conductor_chat",
            "device_scope": "local",
            "device_id": "local",
        }
        try:
            lz.save_session(agent_dir, session)
        except Exception:
            pass
        self._conductor_current_session = session
        self._conductor_render_session(session)
        self._refresh_conductor_sessions()
        if start_runtime:
            def after_ready(ok, _err):
                if ok:
                    self._conductor_seed_runtime_context(session)

            self._conductor_ensure_runtime(show_errors=False, on_ready=after_ready)
        else:
            self._conductor_seed_runtime_context(session)
        self._refresh_conductor_page_state()

    def _on_conductor_session_item_changed(self, current, _previous):
        if current is None:
            return
        raw = current.data(Qt.UserRole)
        if isinstance(raw, dict):
            sid = str(raw.get("id") or "").strip()
        else:
            sid = str(raw or "").strip()
        if not sid:
            return
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not agent_dir:
            return
        try:
            data = lz.load_session(agent_dir, sid)
        except Exception:
            data = None
        if not isinstance(data, dict):
            return
        self._conductor_current_session = data
        self._conductor_render_session(data)
        if hasattr(self, "conductor_chat_title"):
            self.conductor_chat_title.setText(str(data.get("title") or "Conductor"))
        # Restore transcript into master process so context survives restart/switch.
        if self._conductor_proc_alive_quick():
            self._conductor_seed_runtime_context(data)
        else:
            def after_ready(ok, _err):
                if ok:
                    self._conductor_seed_runtime_context(data)

            self._conductor_ensure_runtime(show_errors=False, on_ready=after_ready)

    def _conductor_persist_current(self):
        session = self._conductor_current_session
        agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
        if not isinstance(session, dict) or not agent_dir:
            return
        session["updated_at"] = time.time()
        session["channel_id"] = "conductor"
        session["channel_label"] = lz._usage_channel_label("conductor")
        try:
            lz.save_session(agent_dir, session)
        except Exception:
            pass

    def _conductor_session_seed_items(self, session=None):
        data = session if isinstance(session, dict) else getattr(self, "_conductor_current_session", None)
        if not isinstance(data, dict):
            return []
        items = []
        for bubble in list(data.get("bubbles") or []):
            if not isinstance(bubble, dict):
                continue
            role = str(bubble.get("role") or "assistant").strip().lower()
            text = str(bubble.get("text") or "").strip()
            if not text:
                continue
            if role == "error":
                role = "system"
            elif role not in ("user", "system", "conductor", "assistant"):
                role = "assistant"
            items.append({"role": role, "msg": text, "text": text})
        return items

    def _conductor_seed_runtime_context(self, session=None, *, on_done=None):
        """Push launcher transcript into Conductor process memory (async)."""
        data = session if isinstance(session, dict) else getattr(self, "_conductor_current_session", None)
        sid = str((data or {}).get("id") or "").strip()
        items = self._conductor_session_seed_items(data)

        def worker():
            if not self._conductor_is_running(allow_http=True):
                if callable(on_done):
                    self._conductor_post_ui(lambda: on_done(False, "not running"))
                return
            ok, payload = self._conductor_http_json(
                "POST",
                "/chat/seed",
                {"items": items, "session_id": sid, "replace": True},
                timeout=4.0,
            )

            def done():
                if callable(on_done):
                    try:
                        on_done(bool(ok), payload)
                    except Exception:
                        pass

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-seed", daemon=True).start()

    # ── message area: bind to ChatViewMixin orchestration ───────────────
    def _conductor_bind_chat_surface(self):
        """Temporarily map Conductor widgets onto main-chat attributes.

        ChatViewMixin methods then operate on the Conductor transcript without
        forking a second orchestration stack.
        """
        if not hasattr(self, "_conductor_chat_bind_depth"):
            self._conductor_chat_bind_depth = 0
        if int(self._conductor_chat_bind_depth or 0) <= 0:
            self._conductor_chat_bind_backup = {
                "scroll": getattr(self, "scroll", None),
                "msg_root": getattr(self, "msg_root", None),
                "msg_layout": getattr(self, "msg_layout", None),
                "_rendered_message_rows": getattr(self, "_rendered_message_rows", None),
                "jump_latest_btn": getattr(self, "jump_latest_btn", None),
                "_user_scrolled_up": getattr(self, "_user_scrolled_up", False),
                "_stream_row": getattr(self, "_stream_row", None),
                "_current_stream_text": getattr(self, "_current_stream_text", ""),
                "_pending_stream_text": getattr(self, "_pending_stream_text", None),
                "_current_turn_user_row": getattr(self, "_current_turn_user_row", None),
                "_follow_latest_user_message": getattr(self, "_follow_latest_user_message", False),
                "input_box": getattr(self, "input_box", None),
                "send_btn": getattr(self, "send_btn", None),
                "stop_btn": getattr(self, "stop_btn", None),
                "_busy": getattr(self, "_busy", False),
            }
            self.scroll = getattr(self, "conductor_scroll", None)
            self.msg_root = getattr(self, "conductor_msg_root", None)
            self.msg_layout = getattr(self, "conductor_msg_layout", None)
            if not isinstance(getattr(self, "_conductor_rendered_message_rows", None), list):
                self._conductor_rendered_message_rows = []
            self._rendered_message_rows = self._conductor_rendered_message_rows
            self.jump_latest_btn = getattr(self, "conductor_jump_latest_btn", None)
            self._user_scrolled_up = bool(getattr(self, "_conductor_user_scrolled_up", False))
            self._stream_row = getattr(self, "_conductor_stream_row", None)
            self._current_stream_text = str(getattr(self, "_conductor_stream_text", "") or "")
            self._pending_stream_text = getattr(self, "_conductor_pending_stream_text", None)
            self._current_turn_user_row = getattr(self, "_conductor_turn_user_row", None)
            self._follow_latest_user_message = bool(getattr(self, "_conductor_follow_latest_user", False))
            self.input_box = getattr(self, "conductor_input", None)
            self.send_btn = getattr(self, "conductor_send_btn", None)
            self.stop_btn = getattr(self, "conductor_stop_btn", None)
            self._busy = bool(getattr(self, "_conductor_busy", False))
        self._conductor_chat_bind_depth = int(self._conductor_chat_bind_depth or 0) + 1

    def _conductor_unbind_chat_surface(self):
        depth = int(getattr(self, "_conductor_chat_bind_depth", 0) or 0)
        if depth <= 0:
            return
        depth -= 1
        self._conductor_chat_bind_depth = depth
        # Mirror mutable orchestration state back to conductor fields.
        self._conductor_rendered_message_rows = list(getattr(self, "_rendered_message_rows", None) or [])
        self._conductor_user_scrolled_up = bool(getattr(self, "_user_scrolled_up", False))
        self._conductor_stream_row = getattr(self, "_stream_row", None)
        self._conductor_stream_text = str(getattr(self, "_current_stream_text", "") or "")
        self._conductor_pending_stream_text = getattr(self, "_pending_stream_text", None)
        self._conductor_turn_user_row = getattr(self, "_current_turn_user_row", None)
        self._conductor_follow_latest_user = bool(getattr(self, "_follow_latest_user_message", False))
        self._conductor_busy = bool(getattr(self, "_busy", False))
        if depth > 0:
            return
        backup = getattr(self, "_conductor_chat_bind_backup", None) or {}
        for key, value in backup.items():
            try:
                setattr(self, key, value)
            except Exception:
                pass
        self._conductor_chat_bind_backup = None

    def _conductor_with_chat_surface(self, fn, *args, **kwargs):
        self._conductor_bind_chat_surface()
        try:
            return fn(*args, **kwargs)
        finally:
            self._conductor_unbind_chat_surface()

    def _conductor_clear_messages(self):
        clear = getattr(self, "_clear_messages", None)
        if callable(clear):
            self._conductor_with_chat_surface(clear)
        else:
            layout = getattr(self, "conductor_msg_layout", None)
            if layout is None:
                return
            self._conductor_rendered_message_rows = []
            while layout.count() > 1:
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._conductor_stream_row = None
        self._conductor_stream_text = ""
        self._conductor_pending_stream_text = None
        self._conductor_user_scrolled_up = False

    def _conductor_reset_messages(self, placeholder: str = ""):
        reset = getattr(self, "_reset_chat_area", None)
        if callable(reset):
            # Avoid main-chat side effects (header/token/composer) by binding first
            # and only invoking clear + placeholder ourselves if needed.
            self._conductor_clear_messages()
        else:
            self._conductor_clear_messages()
        if placeholder:
            label = QLabel(placeholder)
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
            label.setObjectName("mutedText")
            label.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 40px 20px;")
            self.conductor_msg_layout.insertWidget(0, label)

    def _conductor_normalize_role(self, role: str) -> str:
        raw = str(role or "").strip().lower()
        if raw == "user":
            return "user"
        if raw == "error":
            return "error"
        return "assistant"

    def _conductor_regenerate_from_row(self, row):
        # Delegate to ChatViewMixin regen (uses bound input_box).
        regen = getattr(self, "_regenerate_from_row", None)
        if callable(regen):
            def _run():
                # Point regen's input write to conductor_input via bind.
                return regen(row)

            self._conductor_with_chat_surface(_run)
            return
        rows = list(getattr(self, "_conductor_rendered_message_rows", None) or [])
        try:
            idx = rows.index(row)
        except ValueError:
            return
        user_text = ""
        for j in range(idx - 1, -1, -1):
            prev = rows[j]
            if str(getattr(prev, "_role", "") or "") == "user":
                user_text = str(getattr(prev, "_text", "") or "")
                break
        if not user_text:
            return
        editor = getattr(self, "conductor_input", None)
        if editor is not None:
            editor.setPlainText(user_text)

    def _conductor_add_message_row(self, role: str, text: str, *, finished: bool = True, auto_scroll: bool = True):
        role_key = self._conductor_normalize_role(role)
        add = getattr(self, "_add_message_row", None)
        if callable(add):
            # Temporarily point regen target at conductor regen.
            original_regen = getattr(self, "_regenerate_from_row", None)

            def _bound_regen(row):
                self._conductor_regenerate_from_row(row)

            def _run():
                if role_key == "assistant":
                    self._regenerate_from_row = _bound_regen
                try:
                    return add(role_key, text, finished=finished, auto_scroll=auto_scroll)
                finally:
                    if original_regen is not None:
                        self._regenerate_from_row = original_regen

            return self._conductor_with_chat_surface(_run)

        on_resend = self._conductor_regenerate_from_row if role_key == "assistant" else None
        row = build_message_row(
            text,
            role_key,
            self.conductor_msg_root,
            on_resend=on_resend,
            avatar_cfg=getattr(self, "cfg", None),
            row_cls=MessageRow,
        )
        setter = getattr(row, "set_finished", None)
        if callable(setter):
            setter(finished)
        insert_at = max(0, self.conductor_msg_layout.count() - 1)
        self.conductor_msg_layout.insertWidget(insert_at, row)
        self._conductor_rendered_message_rows.append(row)
        if auto_scroll:
            self._conductor_scroll_to_bottom()
        return row

    def _conductor_begin_wait_stream(self, placeholder: str = "总管处理中…"):
        """Mirror main-chat streaming placeholder while waiting for HTTP reply."""
        self._conductor_discard_wait_stream()
        if not self._conductor_rendered_message_rows:
            # Ensure empty-state label is gone before stream row.
            self._conductor_clear_messages()
        row = self._conductor_add_message_row("assistant", placeholder, finished=False, auto_scroll=True)
        self._conductor_stream_row = row
        self._conductor_stream_text = placeholder
        self._conductor_set_busy(True)
        return row

    def _conductor_update_wait_stream(self, text: str):
        row = getattr(self, "_conductor_stream_row", None)
        body = str(text or "")
        self._conductor_stream_text = body
        if row is None:
            return
        updater = getattr(row, "update_content", None)
        if callable(updater):
            updater(body or "…", finished=False)
        self._conductor_scroll_to_bottom()

    def _conductor_finish_wait_stream(self, text: str = "", *, as_error: bool = False):
        row = getattr(self, "_conductor_stream_row", None)
        body = str(text or "").strip()
        self._conductor_stream_row = None
        self._conductor_stream_text = ""
        self._conductor_set_busy(False)
        if row is None:
            if body:
                if as_error:
                    self._conductor_append_error_line(body, persist=True)
                else:
                    self._conductor_append_bubble("assistant", body, persist=True)
            return
        if as_error or not body:
            # Drop placeholder row; show error banner if needed.
            rows = getattr(self, "_conductor_rendered_message_rows", None)
            if isinstance(rows, list):
                try:
                    rows.remove(row)
                except ValueError:
                    pass
            try:
                row.setParent(None)
                row.deleteLater()
            except Exception:
                pass
            if as_error and body:
                self._conductor_append_error_line(body, persist=True)
            return
        updater = getattr(row, "update_content", None)
        if callable(updater):
            updater(body, finished=True)
        else:
            setter = getattr(row, "set_finished", None)
            if callable(setter):
                setter(True)
        session = self._conductor_current_session
        if isinstance(session, dict):
            session.setdefault("bubbles", []).append({"role": "assistant", "text": body})
            self._conductor_persist_current()
            self._refresh_conductor_sessions()
        self._conductor_scroll_to_bottom()

    def _conductor_discard_wait_stream(self):
        row = getattr(self, "_conductor_stream_row", None)
        self._conductor_stream_row = None
        self._conductor_stream_text = ""
        if row is None:
            return
        rows = getattr(self, "_conductor_rendered_message_rows", None)
        if isinstance(rows, list):
            try:
                rows.remove(row)
            except ValueError:
                pass
        try:
            row.setParent(None)
            row.deleteLater()
        except Exception:
            pass

    def _conductor_append_error_line(self, text: str, *, persist: bool = True):
        msg = str(text or "").strip()
        if not msg:
            return None
        if msg.startswith("⚠"):
            msg = msg.lstrip("⚠ ").strip()
        session = self._conductor_current_session
        if persist and isinstance(session, dict):
            session.setdefault("bubbles", []).append({"role": "error", "text": msg})
            self._conductor_persist_current()
        if not self._conductor_rendered_message_rows:
            self._conductor_clear_messages()
        append = getattr(self, "_append_chat_error_line", None)
        if callable(append):
            # Use main-chat error banner implementation via surface bind.
            # It may try to persist to current_session — point that temporarily.
            backup_session = getattr(self, "current_session", None)
            backup_persist = getattr(self, "_persist_session", None)

            def _noop_persist(_session):
                return None

            def _run():
                self.current_session = session if isinstance(session, dict) else None
                self._persist_session = _noop_persist
                try:
                    return append(msg, persist=False, auto_scroll=True)
                finally:
                    self.current_session = backup_session
                    if backup_persist is not None:
                        self._persist_session = backup_persist

            return self._conductor_with_chat_surface(_run)
        return self._conductor_add_message_row("error", msg, finished=True, auto_scroll=True)

    def _conductor_on_scroll_changed(self, value: int):
        self._conductor_with_chat_surface(getattr(self, "_on_scroll_changed", lambda _v: None), value)
        self._conductor_user_scrolled_up = bool(getattr(self, "_conductor_user_scrolled_up", False) or getattr(self, "_user_scrolled_up", False))

    def _conductor_refresh_jump_latest_button(self):
        refresh = getattr(self, "_refresh_jump_latest_button", None)
        if callable(refresh):
            self._conductor_with_chat_surface(refresh)
            # Keep button positioned in conductor viewport.
            btn = getattr(self, "conductor_jump_latest_btn", None)
            scroll = getattr(self, "conductor_scroll", None)
            if btn is not None and scroll is not None and btn.isVisible():
                try:
                    vp = scroll.viewport()
                    margin = 16
                    btn.move(max(8, vp.width() - btn.width() - margin), max(8, vp.height() - btn.height() - margin))
                    btn.raise_()
                except Exception:
                    pass
            return
        btn = getattr(self, "conductor_jump_latest_btn", None)
        if btn is not None:
            btn.hide()

    def _conductor_scroll_to_bottom(self, force: bool = False):
        scroll = getattr(self, "_scroll_to_bottom", None)
        if callable(scroll):
            self._conductor_with_chat_surface(scroll, force)
            return
        try:
            bar = self.conductor_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        except Exception:
            pass

    def _conductor_jump_to_latest(self):
        jump = getattr(self, "_jump_to_latest_dialogue", None)
        if callable(jump):
            self._conductor_with_chat_surface(jump)
            return
        self._conductor_user_scrolled_up = False
        self._conductor_scroll_to_bottom(force=True)

    def _conductor_set_busy(self, busy: bool):
        self._conductor_busy = bool(busy)
        # Keep ChatViewMixin-compatible flag when bound.
        if int(getattr(self, "_conductor_chat_bind_depth", 0) or 0) > 0:
            self._busy = bool(busy)
        stop_btn = getattr(self, "conductor_stop_btn", None)
        if stop_btn is not None:
            stop_btn.setEnabled(bool(busy))
        send_btn = getattr(self, "conductor_send_btn", None)
        if send_btn is not None and not bool(getattr(self, "_conductor_start_inflight", False)):
            # Allow send only when not waiting for a reply.
            send_btn.setEnabled(not bool(busy))

    def _conductor_abort_current(self):
        """Best-effort interrupt: drop wait stream; optionally stop process."""
        had_wait = getattr(self, "_conductor_stream_row", None) is not None or bool(getattr(self, "_conductor_busy", False))
        self._conductor_discard_wait_stream()
        self._conductor_set_busy(False)
        stopper = getattr(self, "_stop_channel_process", None)
        if callable(stopper) and self._conductor_proc_alive_quick():
            def worker():
                try:
                    stopper("conductor")
                except Exception:
                    pass

                def done():
                    self._refresh_conductor_page_state()
                    if had_wait:
                        self._conductor_append_bubble("assistant", "已请求中断 Conductor 后台。可重新发送消息。", persist=True)

                self._conductor_post_ui(done)

            threading.Thread(target=worker, name="conductor-abort", daemon=True).start()
        elif had_wait:
            self._conductor_append_bubble("assistant", "已取消等待。", persist=True)

    def _conductor_render_session(self, session):
        bubbles = list((session or {}).get("bubbles") or [])
        if not bubbles:
            self._conductor_reset_messages("直接给总管发消息，总管会调度子 Agent。")
            return
        self._conductor_clear_messages()
        for bubble in bubbles:
            role = str((bubble or {}).get("role") or "assistant").strip().lower()
            text = str((bubble or {}).get("text") or "")
            if text.strip():
                self._conductor_add_message_row(role, text, finished=True, auto_scroll=False)
        self._conductor_user_scrolled_up = False
        self._conductor_scroll_to_bottom(force=True)

    def _conductor_append_bubble(self, role: str, text: str, *, persist=True):
        text = str(text or "").strip()
        if not text:
            return
        role_key = self._conductor_normalize_role(role)
        if role_key == "error":
            self._conductor_append_error_line(text, persist=persist)
            return
        session = self._conductor_current_session
        if not isinstance(session, dict):
            self._conductor_new_session(start_runtime=False)
            session = self._conductor_current_session
        if not isinstance(session, dict):
            return
        if session.get("title") in ("", "Conductor 会话", "新会话") and role_key == "user":
            title = text.replace("\n", " ").strip()
            if len(title) > 30:
                title = title[:30] + "…"
            session["title"] = title or "Conductor 会话"
            if hasattr(self, "conductor_chat_title"):
                self.conductor_chat_title.setText(session["title"])
        if not self._conductor_rendered_message_rows:
            self._conductor_clear_messages()
        session.setdefault("bubbles", []).append({"role": role_key, "text": text})
        self._conductor_add_message_row(role_key, text, finished=True, auto_scroll=True)
        if persist:
            self._conductor_persist_current()
            self._refresh_conductor_sessions()

    # ── subagent cards (upstream left panel) ────────────────────────────
    def _conductor_clear_cards(self):
        layout = getattr(self, "conductor_cards_layout", None)
        if layout is None:
            return
        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._conductor_card_widgets = []

    def _conductor_render_cards(self, items):
        self._conductor_clear_cards()
        layout = getattr(self, "conductor_cards_layout", None)
        if layout is None:
            return
        count = len(items or [])
        if hasattr(self, "conductor_side_hint") and self.conductor_side_hint is not None:
            self.conductor_side_hint.setText(f"{count} 个任务")
        if not items:
            empty = QLabel("当前没有子 Agent 任务。")
            empty.setObjectName("mutedText")
            empty.setWordWrap(True)
            empty.setStyleSheet("padding: 8px 4px;")
            layout.insertWidget(0, empty)
            return
        state_color = {
            "running": C.get("success") or "#10b981",
            "waiting": C.get("warning") or "#f59e0b",
            "failed": C.get("error") or "#ef4444",
            "stopped": C.get("muted") or "#9ca3af",
            "aborted": C.get("muted") or "#9ca3af",
        }
        for item in items:
            status = str(item.get("status") or "stopped").strip().lower() or "stopped"
            color = state_color.get(status, state_color["stopped"])
            card = QFrame()
            card.setObjectName("panelCard")
            card.setStyleSheet(
                f"QFrame#panelCard {{ border-left: 4px solid {color}; "
                f"background: {C.get('layer1') or C.get('panel')}; "
                f"border-radius: {F.get('radius_md', 12)}px; }}"
            )
            col = QVBoxLayout(card)
            col.setContentsMargins(12, 10, 12, 10)
            col.setSpacing(6)
            top = QHBoxLayout()
            sid = QLabel(str(item.get("id") or ""))
            sid.setObjectName("mutedText")
            top.addWidget(sid, 0)
            top.addStretch(1)
            st = QLabel(status)
            st.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
            top.addWidget(st, 0)
            col.addLayout(top)
            prompt = QLabel(str(item.get("prompt") or "").strip() or "(无提示)")
            prompt.setWordWrap(True)
            prompt.setObjectName("softText")
            col.addWidget(prompt)
            reply_text = str(item.get("reply") or "").strip() or "暂无输出"
            reply = QLabel(reply_text)
            reply.setWordWrap(True)
            reply.setObjectName("mutedText")
            reply.setStyleSheet(
                f"background: {C.get('layer2') or C.get('field_bg')}; border-radius: 10px; padding: 8px 10px;"
            )
            reply.setMaximumHeight(160)
            col.addWidget(reply)
            layout.insertWidget(layout.count() - 1, card)
            self._conductor_card_widgets.append(card)

    # ── send / poll ─────────────────────────────────────────────────────
    def _conductor_post_user_message(self, text: str, *, on_done=None, on_error=None):
        def worker():
            ok, payload = self._conductor_http_json("POST", "/chat", {"msg": text, "role": "user"}, timeout=8.0)

            def done():
                if not ok:
                    err = str((payload or {}).get("error") or "发送失败")
                    if callable(on_error):
                        on_error(err)
                    else:
                        self._conductor_finish_wait_stream(err, as_error=True)
                    return
                # Keep wait stream; live text comes from GET /stream while master generates.
                self._conductor_update_wait_stream("总管处理中…")
                if callable(on_done):
                    on_done()
                # Kick an immediate stream pull, then chat finalization.
                if self._conductor_ui_alive():
                    QTimer.singleShot(80, self, self._conductor_pull_stream)
                    QTimer.singleShot(300, self, self._conductor_pull_remote_chat)

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-send", daemon=True).start()

    def _conductor_handle_send(self):
        editor = getattr(self, "conductor_input", None)
        if editor is None:
            return
        if bool(getattr(self, "_conductor_busy", False)):
            return
        text = editor.toPlainText().strip()
        if not text:
            return
        if not isinstance(self._conductor_current_session, dict):
            agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
            if agent_dir and lz.is_valid_agent_dir(agent_dir):
                self._conductor_new_session(start_runtime=False)
            else:
                return
        editor.clear()
        self._conductor_append_bubble("user", text)
        # Same orchestration as main chat: show unfinished assistant row while waiting.
        self._conductor_begin_wait_stream("总管处理中…")

        def finish_err(msg: str):
            self._conductor_finish_wait_stream(msg, as_error=True)

        if self._conductor_proc_alive_quick() or self._conductor_is_running(allow_http=False):
            self._conductor_post_user_message(text, on_error=finish_err)
            return

        def on_ready(ok, err):
            if not ok:
                finish_err(err or "无法启动 Conductor 服务，请检查 API 配置与依赖。")
                return
            self._conductor_post_user_message(text, on_error=finish_err)

        self._conductor_ensure_runtime(show_errors=True, on_ready=on_ready)

    def _conductor_pull_stream(self):
        def worker():
            ok, payload = self._conductor_http_json("GET", "/stream", timeout=1.0)

            def done():
                if ok and isinstance(payload, dict):
                    self._conductor_apply_stream_payload(payload)

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-pull-stream", daemon=True).start()

    def _conductor_pull_remote_chat(self):
        def worker():
            ok, payload = self._conductor_http_json("GET", "/chat?last=100", timeout=2.0)

            def done():
                if ok and isinstance(payload, dict):
                    self._conductor_apply_chat_payload(payload)

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-pull-chat", daemon=True).start()

    def _conductor_pull_subagents(self):
        def worker():
            ok, payload = self._conductor_http_json("GET", "/subagent", timeout=2.0)

            def done():
                if ok and isinstance(payload, dict):
                    self._conductor_apply_sub_payload(payload)
                else:
                    self._conductor_render_cards([])

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-pull-sub", daemon=True).start()

    def _conductor_apply_chat_payload(self, payload: dict):
        items = list((payload or {}).get("items") or [])
        sig = json.dumps([(i.get("id"), i.get("role"), i.get("msg")) for i in items], ensure_ascii=False)
        if sig == getattr(self, "_conductor_chat_sig", ""):
            return
        self._conductor_chat_sig = sig
        session = self._conductor_current_session
        if not isinstance(session, dict):
            return
        existing = {
            (str(b.get("role") or ""), str(b.get("text") or "").strip())
            for b in list(session.get("bubbles") or [])
            if isinstance(b, dict)
        }
        new_texts = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "assistant").strip().lower()
            if role == "user":
                continue
            text = str(item.get("msg") or "").strip()
            if not text or ("assistant", text) in existing:
                continue
            new_texts.append(text)
            existing.add(("assistant", text))
        if not new_texts:
            return
        waiting = getattr(self, "_conductor_stream_row", None)
        if waiting is not None:
            first, *rest = new_texts
            # finish_wait_stream already persists first reply into session bubbles.
            self._conductor_finish_wait_stream(first, as_error=False)
            for extra in rest:
                self._conductor_append_bubble("assistant", extra, persist=True)
        else:
            if not self._conductor_rendered_message_rows:
                self._conductor_clear_messages()
            for text in new_texts:
                session.setdefault("bubbles", []).append({"role": "assistant", "text": text})
                self._conductor_add_message_row("assistant", text, finished=True, auto_scroll=True)
            self._conductor_persist_current()
            self._refresh_conductor_sessions()
        self._conductor_set_busy(False)
        self._conductor_scroll_to_bottom()

    def _conductor_apply_sub_payload(self, payload: dict):
        items = list((payload or {}).get("items") or [])
        sig = json.dumps(
            [(i.get("id"), i.get("status"), (i.get("reply") or "")[:120], (i.get("prompt") or "")[:80]) for i in items],
            ensure_ascii=False,
        )
        if sig == getattr(self, "_conductor_sub_sig", ""):
            return
        self._conductor_sub_sig = sig
        self._conductor_render_cards(items)

    def _conductor_apply_stream_payload(self, payload: dict):
        """Apply live master-agent draft into the waiting assistant bubble."""
        if not isinstance(payload, dict):
            return
        seq = int(payload.get("seq", 0) or 0)
        active = bool(payload.get("active"))
        text = str(payload.get("text") or "")
        done = bool(payload.get("done"))
        last_seq = int(getattr(self, "_conductor_stream_seq", 0) or 0)
        if seq and seq <= last_seq and not done:
            return
        if seq:
            self._conductor_stream_seq = seq
        waiting = getattr(self, "_conductor_stream_row", None)
        if active and text:
            if waiting is None and bool(getattr(self, "_conductor_busy", False)):
                # Recover a stream row if UI lost it.
                self._conductor_begin_wait_stream(text)
            else:
                # Prefer last-turn visible body (strip turn markers lightly).
                shown = text
                try:
                    shown = lz._assistant_visible_markup(text) or text
                except Exception:
                    shown = text
                if not shown.strip():
                    shown = text
                self._conductor_update_wait_stream(shown)
            # Keep poll hot while streaming.
            timer = getattr(self, "_conductor_status_timer", None)
            if timer is not None:
                try:
                    timer.setInterval(250)
                except Exception:
                    pass
            return
        if done and waiting is not None:
            shown = text
            try:
                shown = lz._assistant_visible_markup(text) or text
            except Exception:
                shown = text
            shown = str(shown or "").strip()
            # Master often speaks via later POST /chat; if draft has usable text, finish with it.
            # If draft is empty/noise, keep waiting briefly for chat items from poll.
            if shown and shown not in ("总管处理中…", "…"):
                # Avoid double-persist if the same text already exists in session.
                session = self._conductor_current_session if isinstance(self._conductor_current_session, dict) else {}
                already = any(
                    str(b.get("role") or "") == "assistant" and str(b.get("text") or "").strip() == shown
                    for b in list(session.get("bubbles") or [])
                    if isinstance(b, dict)
                )
                if already:
                    self._conductor_discard_wait_stream()
                    self._conductor_set_busy(False)
                else:
                    self._conductor_finish_wait_stream(shown, as_error=False)
            else:
                # Generation ended without visible draft; clear placeholder soon if no chat arrives.
                self._conductor_update_wait_stream("总管处理中…")
            timer = getattr(self, "_conductor_status_timer", None)
            if timer is not None:
                try:
                    timer.setInterval(800)
                except Exception:
                    pass
            return
        if (not active) and (not done):
            timer = getattr(self, "_conductor_status_timer", None)
            if timer is not None and not bool(getattr(self, "_conductor_busy", False)):
                try:
                    timer.setInterval(1200)
                except Exception:
                    pass

    def _conductor_poll_tick(self):
        if bool(getattr(self, "_conductor_poll_inflight", False)):
            return
        if str(getattr(self, "_main_nav_mode", "") or "") != "conductor":
            return
        self._conductor_poll_inflight = True
        busy = bool(getattr(self, "_conductor_busy", False)) or getattr(self, "_conductor_stream_row", None) is not None

        def worker():
            running = False
            chat_payload = None
            sub_payload = None
            stream_payload = None
            try:
                running = self._conductor_is_running(allow_http=True)
                if running:
                    # Prefer stream first while waiting so UI stays responsive.
                    if busy:
                        _oks, stream_payload = self._conductor_http_json("GET", "/stream", timeout=1.0)
                    _ok1, chat_payload = self._conductor_http_json("GET", "/chat?last=100", timeout=1.5)
                    _ok2, sub_payload = self._conductor_http_json("GET", "/subagent", timeout=1.5)
                    if (not busy) and (not stream_payload):
                        _oks, stream_payload = self._conductor_http_json("GET", "/stream", timeout=0.8)
            except Exception:
                running = False

            def done():
                self._conductor_poll_inflight = False
                self._apply_conductor_runtime_status(running)
                if running:
                    if isinstance(stream_payload, dict):
                        self._conductor_apply_stream_payload(stream_payload)
                    if isinstance(chat_payload, dict):
                        self._conductor_apply_chat_payload(chat_payload)
                    if isinstance(sub_payload, dict):
                        self._conductor_apply_sub_payload(sub_payload)

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-poll", daemon=True).start()

    def _apply_conductor_runtime_status(self, running: bool):
        if bool(getattr(self, "_conductor_start_inflight", False)):
            return
        if hasattr(self, "conductor_status_label") and self.conductor_status_label is not None:
            self.conductor_status_label.setText("后台运行中" if running else "后台未启动（进入页面或发消息时会自动拉起）")
        if hasattr(self, "conductor_runtime_btn") and self.conductor_runtime_btn is not None:
            self.conductor_runtime_btn.setEnabled(True)
            self.conductor_runtime_btn.setText("停止后台" if running else "启动后台")
        if hasattr(self, "conductor_conn_hint") and self.conductor_conn_hint is not None:
            # Keep chat header clean: only show disconnected hint when needed.
            self.conductor_conn_hint.setText("" if running else "后台未就绪")

    def _refresh_conductor_page_state(self):
        # Never do HTTP health checks on the UI thread.
        self._apply_conductor_runtime_status(self._conductor_proc_alive_quick())

    def _conductor_toggle_runtime(self):
        if bool(getattr(self, "_conductor_start_inflight", False)):
            return
        if self._conductor_proc_alive_quick():
            stopper = getattr(self, "_stop_channel_process", None)
            if hasattr(self, "conductor_status_label") and self.conductor_status_label is not None:
                self.conductor_status_label.setText("正在停止后台…")
            if hasattr(self, "conductor_runtime_btn") and self.conductor_runtime_btn is not None:
                self.conductor_runtime_btn.setEnabled(False)
                self.conductor_runtime_btn.setText("停止中…")

            def worker():
                if callable(stopper):
                    try:
                        stopper("conductor")
                    except Exception:
                        pass

                def done():
                    if hasattr(self, "conductor_runtime_btn") and self.conductor_runtime_btn is not None:
                        self.conductor_runtime_btn.setEnabled(True)
                    self._refresh_conductor_page_state()

                self._conductor_post_ui(done)

            threading.Thread(target=worker, name="conductor-stop", daemon=True).start()
            return
        self._conductor_ensure_runtime(show_errors=True)

    def _conductor_refresh_all(self):
        self._refresh_conductor_sessions()
        self._refresh_conductor_page_state()
        # HTTP pulls always off the UI thread via poll helpers.
        def worker():
            if not self._conductor_is_running(allow_http=True):
                def idle():
                    self._conductor_render_cards([])

                self._conductor_post_ui(idle)
                return
            chat_ok, chat_payload = self._conductor_http_json("GET", "/chat?last=100", timeout=2.0)
            sub_ok, sub_payload = self._conductor_http_json("GET", "/subagent", timeout=2.0)

            def done():
                if chat_ok and isinstance(chat_payload, dict):
                    self._conductor_apply_chat_payload(chat_payload)
                if sub_ok and isinstance(sub_payload, dict):
                    self._conductor_apply_sub_payload(sub_payload)

            self._conductor_post_ui(done)

        threading.Thread(target=worker, name="conductor-refresh", daemon=True).start()

    def _show_conductor_page(self):
        self.setWindowTitle("GenericAgent 启动器")
        ensure = getattr(self, "_ensure_conductor_page_built", None)
        if callable(ensure):
            ensure()
        workspace = getattr(self, "_app_workspace", None)
        if workspace is not None and getattr(self, "pages", None) is not None:
            try:
                if self.pages.currentWidget() is not workspace:
                    self.pages.setCurrentWidget(workspace)
            except Exception:
                self.pages.setCurrentWidget(workspace)
        setter = getattr(self, "_set_main_nav", None)
        if callable(setter):
            try:
                setter("conductor", switch_stack=True)
            except TypeError:
                try:
                    setter("conductor")
                except Exception:
                    pass
            except Exception:
                pass
        # Paint the page first; start runtime in background after a tick.
        self._refresh_conductor_sessions()
        if not isinstance(self._conductor_current_session, dict):
            rows = self._conductor_session_rows()
            if rows:
                sid = str(rows[0].get("id") or "").strip()
                agent_dir = str(getattr(self, "agent_dir", "") or "").strip()
                if sid and agent_dir:
                    try:
                        data = lz.load_session(agent_dir, sid)
                    except Exception:
                        data = None
                    if isinstance(data, dict):
                        self._conductor_current_session = data
                        self._conductor_render_session(data)
                        if hasattr(self, "conductor_chat_title"):
                            self.conductor_chat_title.setText(str(data.get("title") or "Conductor"))
            if not isinstance(self._conductor_current_session, dict):
                self._conductor_reset_messages("点左侧「新会话」，或直接输入消息开始。")
        self._refresh_conductor_page_state()

        def _seed_current():
            sess = getattr(self, "_conductor_current_session", None)
            if isinstance(sess, dict):
                self._conductor_seed_runtime_context(sess)

        if self._conductor_proc_alive_quick():
            # Already up: restore session context + pull live cards/chat.
            _seed_current()
            self._conductor_refresh_all()
        else:
            self._conductor_render_cards([])
            if lz.is_valid_agent_dir(getattr(self, "agent_dir", "")):
                def after_ready(ok, _err):
                    if ok:
                        _seed_current()
                        self._conductor_refresh_all()

                try:
                    QTimer.singleShot(
                        0,
                        self,
                        lambda: self._conductor_ensure_runtime(show_errors=False, on_ready=after_ready),
                    )
                except Exception:
                    try:
                        QTimer.singleShot(
                            0,
                            lambda: self._conductor_ensure_runtime(show_errors=False, on_ready=after_ready),
                        )
                    except Exception:
                        self._conductor_ensure_runtime(show_errors=False, on_ready=after_ready)
        timer = getattr(self, "_conductor_status_timer", None)
        if timer is not None and not timer.isActive():
            try:
                timer.start()
            except Exception:
                pass

    def _pause_conductor_status_timer(self):
        timer = getattr(self, "_conductor_status_timer", None)
        if timer is not None and timer.isActive():
            try:
                timer.stop()
            except Exception:
                pass
