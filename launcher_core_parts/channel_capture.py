from __future__ import annotations

import os
import textwrap


def channel_capture_sitecustomize_source() -> str:
    return textwrap.dedent(
        r'''
        import hashlib
        import inspect
        import json
        import os
        import re
        import sys
        import threading
        import time

        _GA_CHANNEL_CAPTURE_INSTALLED = False
        _GA_CHANNEL_CAPTURE_LOCK = threading.RLock()
        _GA_QUEUE_CAPTURE_STATES = {}
        _GA_QUEUE_CAPTURE_CLASS_ORIGINAL_PUT = {}
        _GA_QUEUE_CAPTURE_STATE_MAX = 4096
        _GA_QUEUE_CAPTURE_STATE_TTL_SECONDS = 3600
        _GA_CHANNEL_CAPTURE_SOURCES = {
            "wechat": "wechat",
            "telegram": "telegram",
            "tg": "telegram",
            "discord": "discord",
            "dc": "discord",
            "qq": "qq",
            "feishu": "feishu",
            "fs": "feishu",
            "wecom": "wecom",
            "dingtalk": "dingtalk",
        }
        _GA_CHANNEL_CAPTURE_LABELS = {
            "wechat": "微信",
            "telegram": "Telegram / 纸飞机",
            "discord": "Discord",
            "qq": "QQ",
            "feishu": "飞书",
            "wecom": "企业微信",
            "dingtalk": "钉钉",
        }


        def _ga_agent_dir():
            root = str(os.environ.get("GA_LAUNCHER_AGENT_DIR") or "").strip()
            if root:
                return os.path.abspath(root)
            try:
                return os.path.abspath(os.getcwd())
            except Exception:
                return ""


        def _ga_sessions_dir():
            root = _ga_agent_dir()
            return os.path.join(root, "temp", "launcher_sessions") if root else ""


        def _ga_normalize_source(source):
            key = str(source or "").strip().lower()
            return _GA_CHANNEL_CAPTURE_SOURCES.get(key, "")


        def _ga_hash(value, length=16):
            raw = str(value or "").strip()
            if not raw:
                return ""
            return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[: int(length or 16)]


        def _ga_json_safe(value):
            if isinstance(value, dict):
                return {str(key): _ga_json_safe(val) for key, val in value.items()}
            if isinstance(value, (list, tuple)):
                return [_ga_json_safe(item) for item in value]
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            return str(value)


        def _ga_attr(obj, name, default=""):
            try:
                value = getattr(obj, name)
            except Exception:
                return default
            return value if value is not None else default


        def _ga_dict_get(obj, key, default=""):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return default


        def _ga_text(value):
            if value in (None, ""):
                return ""
            return str(value).strip()


        def _ga_first_value(*values):
            for value in values:
                text = _ga_text(value)
                if text:
                    return text
            return ""


        def _ga_pick(obj, *names):
            for name in names:
                if isinstance(obj, dict):
                    value = obj.get(name)
                else:
                    value = _ga_attr(obj, name, "")
                text = _ga_text(value)
                if text:
                    return text
            return ""


        def _ga_nested_pick(obj, *paths):
            for path in paths:
                cur = obj
                ok = True
                for name in path:
                    if isinstance(cur, dict):
                        cur = cur.get(name)
                    else:
                        cur = _ga_attr(cur, name, None)
                    if cur in (None, ""):
                        ok = False
                        break
                if ok:
                    text = _ga_text(cur)
                    if text:
                        return text
            return ""


        def _ga_cleanup_queue_capture_states_locked(now=None):
            now = time.time() if now is None else float(now or 0)
            expired = []
            for key, state in list(_GA_QUEUE_CAPTURE_STATES.items()):
                if not isinstance(state, dict):
                    expired.append(key)
                    continue
                created_at = float(state.get("created_at", now) or now)
                if state.get("recorded_done") or (now - created_at) > _GA_QUEUE_CAPTURE_STATE_TTL_SECONDS:
                    expired.append(key)
            if len(_GA_QUEUE_CAPTURE_STATES) - len(expired) > _GA_QUEUE_CAPTURE_STATE_MAX:
                survivors = [
                    (float(state.get("created_at", now) or now), key)
                    for key, state in _GA_QUEUE_CAPTURE_STATES.items()
                    if key not in expired and isinstance(state, dict)
                ]
                survivors.sort()
                overflow = len(_GA_QUEUE_CAPTURE_STATES) - len(expired) - _GA_QUEUE_CAPTURE_STATE_MAX
                expired.extend(key for _, key in survivors[:max(0, overflow)])
            for key in expired:
                _GA_QUEUE_CAPTURE_STATES.pop(key, None)


        def _ga_context_from_stack(source):
            channel = _ga_normalize_source(source)
            chat_id = ""
            thread_token = ""
            context_token = ""
            event_id = ""
            user_label = ""
            frame = inspect.currentframe()
            try:
                frame = frame.f_back
                depth = 0
                while frame is not None and depth < 36:
                    local = frame.f_locals
                    if not user_label:
                        for key in (
                            "uid",
                            "open_id",
                            "openid",
                            "sender_id",
                            "senderId",
                            "sender_staff_id",
                            "senderStaffId",
                            "user_id",
                            "userId",
                            "author_id",
                            "authorId",
                            "from_user_id",
                            "fromUserId",
                            "from_wxid",
                        ):
                            value = local.get(key)
                            if value not in (None, ""):
                                user_label = _ga_text(value)
                                break
                    if not event_id:
                        for key in ("msg_id", "msgId", "message_id", "messageId", "event_id", "eventId"):
                            value = local.get(key)
                            if value not in (None, ""):
                                event_id = _ga_text(value)
                                break
                    if not chat_id:
                        chat_id = _ga_first_value(
                            local.get("chat_id"),
                            local.get("chatId"),
                            local.get("conversation_id"),
                            local.get("conversationId"),
                            local.get("open_conversation_id"),
                            local.get("openConversationId"),
                            local.get("group_id"),
                            local.get("groupId"),
                            local.get("group_openid"),
                            local.get("room_id"),
                            local.get("roomid"),
                            local.get("roomId"),
                            local.get("guild_id"),
                            local.get("guildId"),
                            local.get("channel_id"),
                            local.get("channelId"),
                            local.get("uid"),
                        )
                    if not thread_token:
                        thread_token = _ga_first_value(
                            local.get("thread_id"),
                            local.get("threadId"),
                            local.get("message_thread_id"),
                            local.get("messageThreadId"),
                            local.get("topic_id"),
                            local.get("topicId"),
                        )
                    if not context_token:
                        context_token = _ga_text(local.get("context_token"))
                    ctx = local.get("ctx")
                    if not context_token and ctx not in (None, "") and not isinstance(ctx, (dict, list, tuple, set)):
                        context_token = _ga_text(ctx)
                    if isinstance(ctx, dict):
                        if not event_id:
                            event_id = _ga_pick(ctx, "msg_id", "msgId", "message_id", "messageId", "id")
                        if not user_label:
                            user_label = _ga_pick(ctx, "uid", "open_id", "openid", "sender_id", "senderId", "user_id", "userId")
                        if not chat_id:
                            chat_id = _ga_pick(
                                ctx,
                                "chat_id",
                                "chatId",
                                "conversation_id",
                                "conversationId",
                                "group_id",
                                "groupId",
                                "room_id",
                                "roomid",
                                "guild_id",
                                "channel_id",
                            )
                        if not context_token:
                            context_token = _ga_pick(ctx, "context_token")
                    query_obj = local.get("query")
                    if query_obj is not None:
                        msg_obj = _ga_attr(query_obj, "message", None)
                        if not event_id:
                            event_id = _ga_first_value(
                                _ga_attr(query_obj, "id", ""),
                                _ga_attr(msg_obj, "message_id", ""),
                                _ga_attr(msg_obj, "id", ""),
                            )
                        if not chat_id:
                            chat = _ga_attr(msg_obj, "chat", None)
                            chat_id = _ga_first_value(_ga_attr(chat, "id", ""), _ga_attr(msg_obj, "chat_id", ""))
                        if not user_label:
                            user = _ga_attr(query_obj, "from_user", None)
                            user_label = _ga_attr(user, "id", "")
                    msg = local.get("msg")
                    if isinstance(msg, dict):
                        if not event_id:
                            event_id = _ga_pick(msg, "message_id", "messageId", "msgid", "msgId", "id")
                        if not user_label:
                            user_label = _ga_pick(
                                msg,
                                "from_user_id",
                                "fromUserId",
                                "from",
                                "openid",
                                "user_openid",
                                "sender_id",
                                "senderStaffId",
                            )
                        if not chat_id:
                            chat_id = _ga_pick(
                                msg,
                                "chat_id",
                                "chatId",
                                "conversation_id",
                                "conversationId",
                                "group_openid",
                                "group_id",
                                "room_id",
                                "roomid",
                                "guild_id",
                                "channel_id",
                            )
                        if not context_token:
                            context_token = _ga_pick(msg, "context_token")
                    message = local.get("message")
                    if message is not None:
                        if not event_id:
                            event_id = _ga_first_value(_ga_attr(message, "message_id", ""), _ga_attr(message, "id", ""))
                        if not chat_id:
                            msg_chat_id = _ga_attr(message, "chat_id", "")
                            chat_id = _ga_text(msg_chat_id)
                        if not chat_id:
                            chat = _ga_attr(message, "chat", None)
                            chat_id = _ga_text(_ga_attr(chat, "id", ""))
                        if not chat_id:
                            channel_obj = _ga_attr(message, "channel", None)
                            guild_obj = _ga_attr(message, "guild", None)
                            chat_id = _ga_first_value(
                                _ga_attr(guild_obj, "id", ""),
                                _ga_attr(channel_obj, "id", ""),
                            )
                        if not thread_token:
                            thread_token = _ga_first_value(
                                _ga_attr(message, "message_thread_id", ""),
                                _ga_attr(message, "thread_id", ""),
                            )
                        if not user_label:
                            author = _ga_attr(message, "author", None) or _ga_attr(message, "from_user", None)
                            user_label = _ga_first_value(_ga_attr(author, "id", ""), _ga_attr(author, "name", ""))
                    update = local.get("update")
                    if update is not None:
                        msg_obj = _ga_attr(update, "message", None) or _ga_attr(update, "effective_message", None)
                        if not event_id:
                            event_id = _ga_first_value(_ga_attr(msg_obj, "message_id", ""), _ga_attr(msg_obj, "id", ""))
                        if not chat_id:
                            chat = _ga_attr(update, "effective_chat", None) or _ga_attr(msg_obj, "chat", None)
                            chat_id = _ga_text(_ga_attr(chat, "id", ""))
                        if not thread_token:
                            thread_token = _ga_first_value(
                                _ga_attr(msg_obj, "message_thread_id", ""),
                                _ga_attr(msg_obj, "thread_id", ""),
                            )
                        if not user_label:
                            user = _ga_attr(update, "effective_user", None)
                            user_label = _ga_text(_ga_attr(user, "id", ""))
                    data = local.get("data")
                    if data is not None:
                        if not event_id:
                            event_id = _ga_pick(data, "id", "msg_id", "msgId", "message_id", "messageId")
                        if not chat_id:
                            chat_id = _ga_first_value(
                                _ga_pick(
                                    data,
                                    "group_openid",
                                    "group_id",
                                    "groupId",
                                    "chat_id",
                                    "chatId",
                                    "conversation_id",
                                    "conversationId",
                                    "openConversationId",
                                    "room_id",
                                    "roomid",
                                    "guild_id",
                                    "channel_id",
                                ),
                                _ga_nested_pick(
                                    data,
                                    ("message", "chat_id"),
                                    ("message", "chatId"),
                                    ("message", "conversationId"),
                                    ("event", "message", "chat_id"),
                                    ("event", "message", "chatId"),
                                    ("event", "message", "conversationId"),
                                ),
                            )
                        if not chat_id:
                            author = _ga_attr(data, "author", None) or _ga_dict_get(data, "author", {})
                            chat_id = (
                                _ga_attr(author, "member_openid", "")
                                or _ga_attr(author, "user_openid", "")
                                or _ga_attr(author, "id", "")
                                or _ga_dict_get(author, "member_openid", "")
                                or _ga_dict_get(author, "user_openid", "")
                                or _ga_dict_get(author, "id", "")
                            )
                        if not user_label:
                            sender = _ga_nested_pick(
                                data,
                                ("event", "sender", "sender_id", "open_id"),
                                ("event", "sender", "senderId", "openId"),
                                ("sender", "sender_id", "open_id"),
                                ("sender", "senderId", "openId"),
                            )
                            user_label = _ga_first_value(
                                sender,
                                _ga_pick(data, "sender_id", "senderId", "sender_staff_id", "senderStaffId", "user_id", "userId"),
                            )
                    frame = frame.f_back
                    depth += 1
            finally:
                del frame
            parts = [channel]
            if chat_id:
                parts.append(chat_id)
                if thread_token:
                    parts.append(thread_token)
                elif context_token:
                    parts.append(context_token)
            elif user_label:
                parts.append(user_label)
                if context_token:
                    parts.append(context_token)
            elif context_token:
                parts.append(context_token)
            else:
                parts.append("default")
            conversation_id = "|".join(str(part or "").strip() for part in parts if str(part or "").strip())
            return conversation_id or (channel + "|default"), event_id, user_label


        def _ga_session_id(channel, conversation_id):
            safe = re.sub(r"[^a-z0-9_-]+", "_", str(channel or "channel").lower())[:24] or "channel"
            return "channel_%s_%s" % (safe, _ga_hash(conversation_id, 18))


        def _ga_clean_user_text(text):
            value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            hint = "If you need to show files to user, use [FILE:filepath] in your response."
            if value.startswith(hint):
                value = value[len(hint):].lstrip()
            return value.strip()


        def _ga_title(text, channel, conversation_id):
            value = re.sub(r"\s+", " ", str(text or "").strip())
            if value:
                return (value[:34].rstrip() + "...") if len(value) > 34 else value
            return "%s conversation %s" % (channel, _ga_hash(conversation_id, 6) or "default")


        def _ga_load_session(path):
            if not os.path.isfile(path):
                return {}
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}


        def _ga_write_session(path, payload):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = "%s.%s.%s.tmp" % (path, os.getpid(), threading.get_ident())
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(_ga_json_safe(payload), handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)


        def _ga_same_last(bubbles, bubble):
            if not bubbles:
                return False
            last = bubbles[-1] if isinstance(bubbles[-1], dict) else {}
            if str(last.get("role") or "") != str(bubble.get("role") or ""):
                return False
            old_event = str(last.get("external_event_id") or "")
            new_event = str(bubble.get("external_event_id") or "")
            if old_event and new_event and old_event == new_event:
                return True
            return str(last.get("text") or "").strip() == str(bubble.get("text") or "").strip()


        def _ga_agent_state(agent):
            if agent is None:
                return {}
            llmclient = getattr(agent, "llmclient", None)
            backend = getattr(llmclient, "backend", None)
            backend_history = getattr(backend, "history", None)
            if not isinstance(backend_history, list):
                backend_history = []
            agent_history = getattr(agent, "history", None)
            handler = getattr(agent, "handler", None)
            handler_history = getattr(handler, "history_info", None)
            if isinstance(handler_history, list) and len(handler_history) >= len(agent_history or []):
                agent_history = handler_history
            if not isinstance(agent_history, list):
                agent_history = []
            try:
                context_win = max(0, int(getattr(backend, "context_win", 0) or 0)) * 3
            except Exception:
                context_win = 0
            used = 0
            for item in list(backend_history or []):
                try:
                    used += len(json.dumps(item, ensure_ascii=False))
                except Exception:
                    pass
            return {
                "backend_history": _ga_json_safe(list(backend_history or [])),
                "agent_history": _ga_json_safe(list(agent_history or [])),
                "llm_idx": int(getattr(agent, "llm_no", 0) or 0),
                "context_window_chars": context_win,
                "current_input_chars": used,
            }


        def _ga_record(channel, conversation_id, role, text, agent=None, event_id="", user_label=""):
            sessions_dir = _ga_sessions_dir()
            if not sessions_dir or not channel or not conversation_id:
                return
            clean_text = str(text or "").strip()
            if not clean_text:
                return
            sid = _ga_session_id(channel, conversation_id)
            path = os.path.join(sessions_dir, sid + ".json")
            now = time.time()
            with _GA_CHANNEL_CAPTURE_LOCK:
                session = _ga_load_session(path)
                created = float(session.get("created_at", now) or now)
                bubbles = list(session.get("bubbles") or [])
                bubble = {
                    "role": role,
                    "text": clean_text,
                    "source": channel,
                    "created_at": now,
                }
                if event_id:
                    bubble["external_event_id"] = _ga_hash(event_id, 16)
                if user_label and role == "user":
                    bubble["external_user_hash"] = _ga_hash(user_label, 16)
                if not _ga_same_last(bubbles, bubble):
                    bubbles.append(bubble)
                bubbles = bubbles[-200:]
                user_turns = sum(1 for item in bubbles if isinstance(item, dict) and item.get("role") == "user")
                label = _GA_CHANNEL_CAPTURE_LABELS.get(channel, channel)
                session.update(
                    {
                        "id": sid,
                        "title": session.get("title") or _ga_title(clean_text if role == "user" else "", channel, conversation_id),
                        "created_at": created,
                        "updated_at": now,
                        "session_kind": "channel_conversation",
                        "session_source_label": channel,
                        "channel_id": channel,
                        "channel_label": label,
                        "device_scope": "local",
                        "device_id": "local",
                        "device_name": "local",
                        "bubbles": bubbles,
                    }
                )
                meta = dict(session.get("channel_conversation") or {})
                meta.update(
                    {
                        "version": 1,
                        "channel_id": channel,
                        "external_thread_hash": _ga_hash(conversation_id, 16),
                        "updated_at": now,
                    }
                )
                session["channel_conversation"] = meta
                state = _ga_agent_state(agent) if role == "assistant" else {}
                if state:
                    session["backend_history"] = list(state.get("backend_history") or [])
                    session["agent_history"] = list(state.get("agent_history") or [])
                    session["llm_idx"] = int(state.get("llm_idx", 0) or 0)
                    snapshot = dict(session.get("snapshot") or {})
                    snapshot.update(
                        {
                            "version": 1,
                            "kind": "turn_complete",
                            "captured_at": now,
                            "turns": user_turns,
                            "llm_idx": int(session.get("llm_idx", 0) or 0),
                            "process_pid": os.getpid(),
                            "has_backend_history": bool(session.get("backend_history")),
                            "has_agent_history": bool(session.get("agent_history")),
                            "context_window_chars": int(state.get("context_window_chars", 0) or 0),
                            "current_input_chars": int(state.get("current_input_chars", 0) or 0),
                        }
                    )
                    session["snapshot"] = snapshot
                else:
                    session.setdefault("backend_history", [])
                    session.setdefault("agent_history", [])
                    session.setdefault("llm_idx", 0)
                    snapshot = dict(session.get("snapshot") or {})
                    snapshot.update(
                        {
                            "version": 1,
                            "kind": snapshot.get("kind") or "channel_conversation",
                            "captured_at": now,
                            "turns": user_turns,
                            "llm_idx": int(session.get("llm_idx", 0) or 0),
                            "process_pid": os.getpid(),
                            "has_backend_history": bool(session.get("backend_history")),
                            "has_agent_history": bool(session.get("agent_history")),
                        }
                    )
                    session["snapshot"] = snapshot
                usage = dict(session.get("token_usage") or {})
                usage.setdefault("events", [])
                usage["channel_id"] = channel
                usage["channel_label"] = label
                usage["turns"] = user_turns
                session["token_usage"] = usage
                _ga_write_session(path, session)


        class _GAQueueProxy:
            def __init__(self, target, agent, channel, conversation_id, event_id):
                self._target = target
                self._agent = agent
                self._channel = channel
                self._conversation_id = conversation_id
                self._event_id = event_id
                self._recorded_done = False

            def _maybe_record(self, item):
                if self._recorded_done or not isinstance(item, dict) or "done" not in item:
                    return item
                self._recorded_done = True
                text = str(item.get("done") or "").strip()
                if not text:
                    return item

                def worker():
                    try:
                        deadline = time.time() + 1.5
                        while bool(getattr(self._agent, "is_running", False)) and time.time() < deadline:
                            time.sleep(0.05)
                        _ga_record(self._channel, self._conversation_id, "assistant", text, agent=self._agent, event_id=self._event_id)
                    except Exception as exc:
                        try:
                            print("[launcher channel capture] assistant record failed: %s: %s" % (type(exc).__name__, exc))
                        except Exception:
                            pass

                threading.Thread(target=worker, name="launcher-channel-capture", daemon=True).start()
                return item

            def get(self, *args, **kwargs):
                return self._maybe_record(self._target.get(*args, **kwargs))

            def get_nowait(self):
                return self._maybe_record(self._target.get_nowait())

            def __getattr__(self, name):
                return getattr(self._target, name)


        def _ga_record_assistant_async(agent, channel, conversation_id, event_id, text):
            clean_text = str(text or "").strip()
            if not clean_text:
                return

            def worker():
                try:
                    deadline = time.time() + 1.5
                    while bool(getattr(agent, "is_running", False)) and time.time() < deadline:
                        time.sleep(0.05)
                    _ga_record(channel, conversation_id, "assistant", clean_text, agent=agent, event_id=event_id)
                except Exception as exc:
                    try:
                        print("[launcher channel capture] assistant record failed: %s: %s" % (type(exc).__name__, exc))
                    except Exception:
                        pass

            threading.Thread(target=worker, name="launcher-channel-capture", daemon=True).start()


        def _ga_patch_display_queue(dq, agent, channel, conversation_id, event_id):
            if dq is None:
                return dq
            if getattr(dq, "_ga_launcher_channel_capture_put_patched", False):
                return dq
            original_put = getattr(dq, "put", None)
            if not callable(original_put):
                if callable(getattr(dq, "get", None)) or callable(getattr(dq, "get_nowait", None)):
                    return _GAQueueProxy(dq, agent, channel, conversation_id, event_id)
                return dq
            recorded_done = {"value": False}

            def patched_put(item, *args, **kwargs):
                result = original_put(item, *args, **kwargs)
                if (not recorded_done["value"]) and isinstance(item, dict) and "done" in item:
                    text = str(item.get("done") or "").strip()
                    if text:
                        recorded_done["value"] = True
                        _ga_record_assistant_async(agent, channel, conversation_id, event_id, text)
                return result

            try:
                dq.put = patched_put
                dq._ga_launcher_channel_capture_put_patched = True
                return dq
            except Exception:
                return _ga_patch_display_queue_class(dq, agent, channel, conversation_id, event_id)


        def _ga_patch_display_queue_class(dq, agent, channel, conversation_id, event_id):
            cls = getattr(dq, "__class__", None)
            if cls is None:
                return _GAQueueProxy(dq, agent, channel, conversation_id, event_id)
            original_put = getattr(cls, "put", None)
            if not callable(original_put):
                return _GAQueueProxy(dq, agent, channel, conversation_id, event_id)
            key = id(dq)
            with _GA_CHANNEL_CAPTURE_LOCK:
                _ga_cleanup_queue_capture_states_locked()
                _GA_QUEUE_CAPTURE_STATES[key] = {
                    "agent": agent,
                    "channel": channel,
                    "conversation_id": conversation_id,
                    "event_id": event_id,
                    "recorded_done": False,
                    "created_at": time.time(),
                }
                if cls in _GA_QUEUE_CAPTURE_CLASS_ORIGINAL_PUT:
                    return dq
                _GA_QUEUE_CAPTURE_CLASS_ORIGINAL_PUT[cls] = original_put

            def class_patched_put(self, item, *args, **kwargs):
                result = original_put(self, item, *args, **kwargs)
                with _GA_CHANNEL_CAPTURE_LOCK:
                    state = _GA_QUEUE_CAPTURE_STATES.get(id(self))
                if (
                    isinstance(state, dict)
                    and (not state.get("recorded_done"))
                    and isinstance(item, dict)
                    and "done" in item
                ):
                    text = str(item.get("done") or "").strip()
                    if text:
                        with _GA_CHANNEL_CAPTURE_LOCK:
                            state["recorded_done"] = True
                            _GA_QUEUE_CAPTURE_STATES.pop(id(self), None)
                        _ga_record_assistant_async(
                            state.get("agent"),
                            state.get("channel"),
                            state.get("conversation_id"),
                            state.get("event_id"),
                            text,
                        )
                return result

            try:
                setattr(cls, "put", class_patched_put)
                return dq
            except Exception:
                with _GA_CHANNEL_CAPTURE_LOCK:
                    if _GA_QUEUE_CAPTURE_CLASS_ORIGINAL_PUT.get(cls) is original_put:
                        _GA_QUEUE_CAPTURE_CLASS_ORIGINAL_PUT.pop(cls, None)
                    _GA_QUEUE_CAPTURE_STATES.pop(key, None)
                return _GAQueueProxy(dq, agent, channel, conversation_id, event_id)


        def _ga_patch_agentmain(mod):
            agent_cls = getattr(mod, "GeneraticAgent", None) or getattr(mod, "GenericAgent", None)
            if agent_cls is None or getattr(agent_cls, "_ga_launcher_channel_capture_patched", False):
                return mod
            original_put_task = getattr(agent_cls, "put_task", None)
            if not callable(original_put_task):
                return mod

            def patched_put_task(self, *args, **kwargs):
                query = args[0] if args else kwargs.get("query", "")
                source = kwargs.get("source", args[1] if len(args) > 1 else "user")
                channel = _ga_normalize_source(source)
                if not channel:
                    return original_put_task(self, *args, **kwargs)
                conversation_id, event_id, user_label = _ga_context_from_stack(source)
                user_text = _ga_clean_user_text(query)
                try:
                    _ga_record(channel, conversation_id, "user", user_text, agent=None, event_id=event_id, user_label=user_label)
                except Exception as exc:
                    try:
                        print("[launcher channel capture] user record failed: %s: %s" % (type(exc).__name__, exc))
                    except Exception:
                            pass
                dq = original_put_task(self, *args, **kwargs)
                return _ga_patch_display_queue(dq, self, channel, conversation_id, event_id)

            agent_cls.put_task = patched_put_task
            agent_cls._ga_launcher_channel_capture_patched = True
            if hasattr(mod, "GeneraticAgent"):
                mod.GeneraticAgent = agent_cls
            if hasattr(mod, "GenericAgent"):
                mod.GenericAgent = agent_cls
            return mod


        def _ga_install_import_hook():
            global _GA_CHANNEL_CAPTURE_INSTALLED
            if _GA_CHANNEL_CAPTURE_INSTALLED:
                return
            _GA_CHANNEL_CAPTURE_INSTALLED = True
            import builtins
            original_import = builtins.__import__
            existing_agentmain = sys.modules.get("agentmain")
            if existing_agentmain is not None:
                try:
                    _ga_patch_agentmain(existing_agentmain)
                except Exception:
                    pass

            def patched_import(name, globals=None, locals=None, fromlist=(), level=0):
                mod = original_import(name, globals, locals, fromlist, level)
                try:
                    root_name = str(name or "").split(".", 1)[0]
                    if root_name == "agentmain":
                        target = sys.modules.get("agentmain") or mod
                        _ga_patch_agentmain(target)
                except Exception:
                    pass
                return mod

            builtins.__import__ = patched_import


        _ga_install_import_hook()
        '''
    ).strip() + "\n"


def install_channel_capture_runtime(agent_dir: str) -> str:
    root = os.path.abspath(str(agent_dir or "").strip()) if str(agent_dir or "").strip() else ""
    if not root or not os.path.isdir(root):
        return ""
    runtime_dir = os.path.join(root, "temp", "launcher_channel_capture")
    os.makedirs(runtime_dir, exist_ok=True)
    sitecustomize_path = os.path.join(runtime_dir, "sitecustomize.py")
    source = channel_capture_sitecustomize_source()
    existing = ""
    if os.path.isfile(sitecustomize_path):
        try:
            with open(sitecustomize_path, "r", encoding="utf-8") as handle:
                existing = handle.read()
        except Exception:
            existing = ""
    if existing != source:
        with open(sitecustomize_path, "w", encoding="utf-8") as handle:
            handle.write(source)
    return runtime_dir


def channel_capture_env(base_env: dict | None, agent_dir: str, *, pathsep: str | None = None) -> dict:
    env = dict(base_env or os.environ)
    runtime_dir = install_channel_capture_runtime(agent_dir)
    if runtime_dir:
        sep = os.pathsep if pathsep is None else str(pathsep)
        existing = str(env.get("PYTHONPATH") or "").strip()
        env["PYTHONPATH"] = runtime_dir if not existing else runtime_dir + sep + existing
        env["GA_LAUNCHER_CHANNEL_CAPTURE"] = "1"
        env["GA_LAUNCHER_AGENT_DIR"] = os.path.abspath(str(agent_dir or "").strip())
    return env
