from __future__ import annotations

import re

_TURN_RE = re.compile(r"(\**LLM Running \(Turn \d+\) \.\.\.\*\**)")
_CLEAN_BLOCK_RE = re.compile(r"(?P<fence>`{3,})[\s\S]*?(?P=fence)|<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_SUMMARY_RE = re.compile(r"<summary>\s*((?:(?!<summary>).)*?)\s*</summary>", re.DOTALL)

_RE_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_RE_SUMMARY = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL | re.IGNORECASE)
_RE_TOOLUSE = re.compile(r"<tool_use>(.*?)</tool_use>", re.DOTALL | re.IGNORECASE)
_RE_FILE_CONTENT = re.compile(r"<file_content>(.*?)</file_content>", re.DOTALL | re.IGNORECASE)
_FILE_TAG_RE = re.compile(r"\[FILE:([^\]]+)\]")
# Upstream protocol tail (ga.do_no_tool / conductor). TUI & desktop_bridge strip it;
# often arrives fenced with 3-5 backticks, which our code-block renderer would box.
_FINAL_RESPONSE_MARKER_RE = re.compile(
    r"\n*(?:`{3,5}[ \t]*\n*)?\[Info\]\s*Final response to user\.\s*(?:\n*`{3,5}[ \t]*)?\s*$",
    re.IGNORECASE,
)
_INFO_STATUS_LINE_RE = re.compile(r"^\s*\[(?:Info|Status)\][^\n]*\n?", re.MULTILINE | re.IGNORECASE)
# Upstream llmcore streams API/network failures as assistant text, not exceptions.
# Examples:
#   !!!Error: HTTP 401: {"error":{"code":"invalid_api_key",...}}
#   !!!Error: Timeout: ...
#   !!!Error: SSE ...
#   [!!! 流异常中断 ConnectionError: ... !!!]
#   [!!! 流异常中断，未收到完整响应 !!!]
#   [Error: Claude refusal]
# Do NOT treat tool-body "Error: File not found" as transport failures.
# Only the error token itself — never swallow following normal paragraphs.
# Multi-line JSON bodies are absorbed only while lines look like JSON continuation.
_LLM_BANG_ERROR_LINE_RE = re.compile(r"(?m)^[ \t]*!!!Error:\s*(?P<msg>.*)$", re.IGNORECASE)
_LLM_STREAM_ABORT_RE = re.compile(
    r"(?:^|\n)\s*\[!!!\s*流异常中断(?P<msg>[^\]]*?)!!!\]\s*",
    re.DOTALL,
)
_LLM_BRACKET_ERROR_RE = re.compile(
    r"(?:^|\n)\s*\[Error:\s*(?P<msg>[^\]]+)\]\s*",
    re.IGNORECASE,
)
_LLM_ERROR_PREFIX_RE = re.compile(r"^\s*(?:!!!Error:|Error:)\s*", re.IGNORECASE)
_LLM_JSON_CONT_LINE_RE = re.compile(r"""^[ \t]*(\{|\}|\[|\]|,|".*"|[\w.*+-]+\s*:)""")
_LLM_TRANSPORT_HINT_RE = re.compile(
    r"(?i)("
    r"HTTP\s+\d{3}"
    r"|invalid[_ ]?api[_ ]?key"
    r"|api[_ ]?key"
    r"|unauthorized"
    r"|forbidden"
    r"|rate[_ ]?limit"
    r"|timeout"
    r"|timed?\s*out"
    r"|connection"
    r"|chunkedencoding"
    r"|SSE\b"
    r"|empty response"
    r"|Claude refusal"
    r"|未收到完整响应"
    r"|流异常中断"
    r")"
)


def fold_turns(text):
    parts = _TURN_RE.split(text or "")
    if len(parts) < 4:
        return [{"type": "text", "content": text or ""}]
    segments = []
    if parts[0].strip():
        segments.append({"type": "text", "content": parts[0]})
    turns = []
    for i in range(1, len(parts), 2):
        marker = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        turns.append((marker, content))
    for idx, (marker, content) in enumerate(turns):
        if idx < len(turns) - 1:
            cleaned = _CLEAN_BLOCK_RE.sub("", content)
            match = _SUMMARY_RE.search(cleaned)
            if match:
                title = match.group(1).strip().split("\n")[0]
                if len(title) > 50:
                    title = title[:50] + "..."
            else:
                title = marker.strip("*")
            segments.append({"type": "fold", "title": title, "content": content})
        else:
            segments.append({"type": "text", "content": marker + content})
    return segments


def _strip_protocol_info_markers(text):
    """Remove conductor/GA protocol markers that are not user-facing content."""
    raw = str(text or "")
    if not raw:
        return ""
    # Final-marker regex already eats optional surrounding fences; do not strip bare
    # ``` lines globally or real markdown code fences would be broken.
    cleaned = _FINAL_RESPONSE_MARKER_RE.sub("", raw)
    cleaned = _INFO_STATUS_LINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _looks_like_llm_transport_error(message: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return False
    return bool(_LLM_TRANSPORT_HINT_RE.search(text))


def _clean_extracted_error_message(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    text = text.strip(" ,;，；")
    text = re.sub(r"\s+", " ", text.replace("\r", " ").replace("\n", " ")).strip()
    return text


def _consume_bang_error_block(lines, start_idx: int):
    """Return (error_message, end_idx_exclusive) for a !!!Error: line at start_idx.

    Keeps following normal paragraphs out of the error message. Only continues
    onto subsequent lines when they look like JSON / structured error payload.
    """
    if start_idx < 0 or start_idx >= len(lines):
        return "", start_idx
    head = str(lines[start_idx] or "")
    match = _LLM_BANG_ERROR_LINE_RE.match(head)
    if not match:
        return "", start_idx
    parts = [str(match.group("msg") or "")]
    idx = start_idx + 1
    open_braces = parts[0].count("{") - parts[0].count("}")
    open_brackets = parts[0].count("[") - parts[0].count("]")
    # Continue only for incomplete JSON-ish payloads (common for HTTP error bodies).
    while idx < len(lines) and (open_braces > 0 or open_brackets > 0):
        nxt = str(lines[idx] or "")
        if not nxt.strip():
            # Blank line ends the error block; normal body may follow.
            break
        if _LLM_BANG_ERROR_LINE_RE.match(nxt) or nxt.lstrip().startswith(("[!!!", "[Error:")):
            break
        if not _LLM_JSON_CONT_LINE_RE.match(nxt) and open_braces <= 0 and open_brackets <= 0:
            break
        parts.append(nxt)
        open_braces += nxt.count("{") - nxt.count("}")
        open_brackets += nxt.count("[") - nxt.count("]")
        idx += 1
        if idx - start_idx > 40:
            break
    msg = _clean_extracted_error_message("\n".join(parts))
    return msg, idx


def _extract_llm_stream_error(text):
    """Split upstream llmcore stream errors out of assistant body text.

    Returns (body_without_error, error_message). error_message is empty when
    the text does not look like an llmcore failure payload.

    Important: never swallow normal paragraphs that follow a !!!Error line.
    """
    raw = str(text or "")
    if not raw:
        return "", ""

    errors = []
    src_lines = raw.splitlines(keepends=True)
    plain_lines = [ln.rstrip("\r\n") for ln in src_lines]
    rebuilt = []
    i = 0
    while i < len(src_lines):
        if _LLM_BANG_ERROR_LINE_RE.match(src_lines[i]):
            msg, end = _consume_bang_error_block(plain_lines, i)
            if msg:
                errors.append(msg)
                i = end
                continue
        rebuilt.append(src_lines[i])
        i += 1
    body = "".join(rebuilt)

    def _strip_matches(pattern, source, *, require_transport=False, default_msg=""):
        nonlocal body
        found = []
        for match in list(pattern.finditer(source)):
            msg = _clean_extracted_error_message(match.group("msg") if "msg" in match.groupdict() else match.group(0))
            if not msg:
                msg = default_msg
            if require_transport and not _looks_like_llm_transport_error(msg):
                continue
            if not msg:
                continue
            found.append(msg)
            body = body.replace(match.group(0), "\n", 1)
        return found

    errors.extend(_strip_matches(_LLM_STREAM_ABORT_RE, body, default_msg="未收到完整响应"))
    errors.extend(_strip_matches(_LLM_BRACKET_ERROR_RE, body, require_transport=True))

    if not errors:
        stripped = raw.strip()
        bare = _TURN_RE.sub("", stripped).strip()
        if _LLM_ERROR_PREFIX_RE.match(bare) and _looks_like_llm_transport_error(bare):
            first_line = bare.splitlines()[0] if bare else ""
            rest_lines = bare.splitlines()[1:]
            rest = "\n".join(rest_lines).strip()
            # If rest is normal prose (not JSON continuation), keep it as body.
            if rest and not (
                first_line.count("{") > first_line.count("}")
                or first_line.count("[") > first_line.count("]")
                or (rest_lines and _LLM_JSON_CONT_LINE_RE.match(rest_lines[0]))
            ):
                msg = _clean_extracted_error_message(_LLM_ERROR_PREFIX_RE.sub("", first_line, count=1))
                if msg:
                    return rest, msg
            msg = _clean_extracted_error_message(_LLM_ERROR_PREFIX_RE.sub("", bare, count=1))
            if msg:
                return "", msg
        fenced = re.fullmatch(
            r"(?:\*{0,2}LLM Running \(Turn \d+\) \.\.\.\*{0,2}\s*)?```(?:\w+)?\s*(?P<body>[\s\S]+?)\s*```\s*",
            bare,
            flags=re.IGNORECASE,
        )
        if fenced:
            body_msg = _clean_extracted_error_message(fenced.group("body"))
            if body_msg and (
                " @ " in body_msg
                or body_msg.startswith(("Traceback", "Exception", "Error", "TypeError", "ValueError", "RuntimeError", "HTTPError", "KeyError"))
                or _looks_like_llm_transport_error(body_msg)
            ):
                return "", body_msg
        return raw, ""

    body = _TURN_RE.sub("", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body, _clean_extracted_error_message(errors[-1])


def _normalize_markup(text):
    if not text:
        return ""
    text = _RE_THINKING.sub("", text)
    text = _RE_SUMMARY.sub(lambda m: f"\n> {m.group(1).strip()}\n", text)
    text = _RE_TOOLUSE.sub(lambda m: f"\n```tool_use\n{m.group(1).strip()}\n```\n", text)
    text = _RE_FILE_CONTENT.sub(lambda m: f"\n```file_content\n{m.group(1).strip()}\n```\n", text)
    text = _strip_protocol_info_markers(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _assistant_visible_markup(text):
    raw = text or ""
    summaries = [m.strip() for m in _RE_SUMMARY.findall(raw) if m.strip()]
    visible = _RE_SUMMARY.sub("", raw)
    visible = _normalize_markup(visible)
    visible = _FILE_TAG_RE.sub(r"\1", visible).strip()
    if visible:
        return visible
    return "\n\n".join(summaries).strip()


def _strip_turn_marker(text):
    return _TURN_RE.sub("", text or "", count=1).strip()


def _turn_marker_title(text):
    m = _TURN_RE.search(text or "")
    if not m:
        return ""
    return m.group(1).strip("*").strip()
