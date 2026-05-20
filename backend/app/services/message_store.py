"""会话消息：内存 + 本地 JSON 文件持久化（单用户场景，默认已「登录」，按 thread_id 分文件）。"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = asyncio.Lock()
# thread_id -> list[{"role": "user"|"assistant", "content": str}]
_store: dict[str, list[dict[str, str]]] = {}


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sessions_dir() -> Path:
    d = _backend_root() / "data" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _thread_file(thread_id: str) -> Path:
    """thread_id 映射为安全文件名（避免路径穿越）。"""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", thread_id).strip("._-")[:180]
    if not safe:
        safe = "default"
    return _sessions_dir() / f"{safe}.json"


def _mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


def _read_disk_snapshot(path: Path) -> dict[str, Any] | None:
    """读取单个会话文件，返回 thread_id、messages、title、updated_at；损坏则 None。"""
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, UnicodeError):
        return None
    mtime_iso = _mtime_iso(path)
    if isinstance(raw, dict) and isinstance(raw.get("messages"), list):
        tid = str(raw.get("thread_id") or path.stem).strip() or path.stem
        msgs = _normalize_messages(raw["messages"])
        title = str(raw.get("title") or "").strip()
        updated = str(raw.get("updated_at") or "").strip() or mtime_iso
        return {"thread_id": tid, "messages": msgs, "title": title, "updated_at": updated}
    if isinstance(raw, list):
        msgs = _normalize_messages(raw)
        return {
            "thread_id": path.stem,
            "messages": msgs,
            "title": "",
            "updated_at": mtime_iso,
        }
    return None


def _load_disk_unsafe(thread_id: str) -> list[dict[str, str]]:
    path = _thread_file(thread_id)
    snap = _read_disk_snapshot(path)
    if not snap:
        return []
    return list(snap["messages"])


def _derive_title(messages: list[dict[str, str]]) -> str:
    for m in messages:
        if m.get("role") == "user":
            t = (m.get("content") or "").strip().replace("\n", " ")
            if t:
                return t[:80]
    return "新对话"


def _save_disk_unsafe(thread_id: str, messages: list[dict[str, str]]) -> None:
    path = _thread_file(thread_id)
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "thread_id": thread_id,
        "updated_at": now,
        "title": _derive_title(messages),
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _delete_disk_unsafe(thread_id: str) -> None:
    path = _thread_file(thread_id)
    if path.is_file():
        path.unlink()


def _touch_unsafe(thread_id: str) -> list[dict[str, str]]:
    """保证 thread_id 在内存中有列表；若冷启动则尝试从磁盘加载。"""
    if thread_id not in _store:
        _store[thread_id] = _load_disk_unsafe(thread_id)
    return _store[thread_id]


def _normalize_messages(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in raw:
        role = str(m.get("role", ""))
        if role not in ("user", "assistant", "system"):
            continue
        content = m.get("content")
        if content is None:
            continue
        out.append({"role": role, "content": str(content)})
    return out


async def get_thread_messages(thread_id: str) -> list[dict[str, str]]:
    async with _lock:
        return list(_touch_unsafe(thread_id))


async def append_exchange(
    thread_id: str,
    user_content: str,
    assistant_content: str,
) -> None:
    async with _lock:
        hist = _touch_unsafe(thread_id)
        hist.append({"role": "user", "content": user_content})
        hist.append({"role": "assistant", "content": assistant_content})
        _save_disk_unsafe(thread_id, hist)


async def clear_thread(thread_id: str) -> None:
    async with _lock:
        _store.pop(thread_id, None)
        _delete_disk_unsafe(thread_id)


async def ensure_session(thread_id: str) -> None:
    """在磁盘上创建空会话（便于左侧列表立即出现「新对话」）。"""
    async with _lock:
        path = _thread_file(thread_id)
        if path.is_file():
            _touch_unsafe(thread_id)
            return
        _store[thread_id] = []
        _save_disk_unsafe(thread_id, [])


async def list_sessions() -> list[dict[str, Any]]:
    """列出 data/sessions 下全部会话，按文件修改时间倒序。"""
    async with _lock:
        d = _sessions_dir()
        paths = sorted(
            (p for p in d.glob("*.json") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for path in paths:
            snap = _read_disk_snapshot(path)
            if not snap:
                continue
            tid = snap["thread_id"]
            msgs: list[dict[str, str]] = snap["messages"]
            title = str(snap.get("title") or "").strip()
            if not title:
                title = _derive_title(msgs) if msgs else "新对话"
            out.append(
                {
                    "thread_id": tid,
                    "title": title[:120],
                    "updated_at": snap["updated_at"],
                    "message_count": len(msgs),
                }
            )
        return out


def rough_token_estimate(text: str) -> int:
    """与 frontend/src/contextUsage.js 中 roughTokenEstimate 对齐的粗略 token 数（用于截断预算）。"""
    if not text:
        return 0
    t = 0.0
    for ch in text:
        c = ord(ch)
        if (0x4E00 <= c <= 0x9FFF) or (0x3400 <= c <= 0x4DBF):
            t += 1.0 / 1.5
        elif ch.isspace():
            t += 0.08
        else:
            t += 0.28
    return max(0, round(t))


def drop_empty_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """去掉无内容的条目，避免空 assistant 干扰多轮理解。"""
    out: list[dict[str, str]] = []
    for m in history:
        if str(m.get("content") or "").strip():
            out.append(m)
    return out


# 用户可能多次粘贴相近长文（前缀略不同），仅保留最后一次超长用户消息
_LONG_USER_MIN_CHARS = 600
_LONG_USER_KEEP_COUNT = 1


def collapse_repeated_long_user_pastes(
    history: list[dict[str, str]],
    min_chars: int = _LONG_USER_MIN_CHARS,
    keep: int = _LONG_USER_KEEP_COUNT,
) -> list[dict[str, str]]:
    long_indices = [
        i
        for i, m in enumerate(history)
        if m.get("role") == "user" and len(str(m.get("content") or "")) >= min_chars
    ]
    if len(long_indices) <= keep:
        return list(history)

    drop_indices = set(long_indices[: len(long_indices) - keep])
    skip: set[int] = set()
    for i in drop_indices:
        skip.add(i)
        if i + 1 < len(history) and history[i + 1].get("role") == "assistant":
            skip.add(i + 1)
    return [m for i, m in enumerate(history) if i not in skip]


def dedupe_repeated_user_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    相同用户正文只保留最后一次（及紧随其后的 assistant）。
    用户可能重复粘贴大段文本，磁盘仍保留全量，仅压缩本次 API 上下文。
    """
    if len(history) < 2:
        return list(history)

    last_idx_by_content: dict[str, int] = {}
    for i, m in enumerate(history):
        if m.get("role") != "user":
            continue
        key = str(m.get("content") or "").strip()
        if key:
            last_idx_by_content[key] = i

    skip: set[int] = set()
    for i, m in enumerate(history):
        if m.get("role") != "user":
            continue
        key = str(m.get("content") or "").strip()
        if not key or last_idx_by_content.get(key) == i:
            continue
        skip.add(i)
        if i + 1 < len(history) and history[i + 1].get("role") == "assistant":
            skip.add(i + 1)

    return [m for i, m in enumerate(history) if i not in skip]


def prepare_history_for_api(
    history: list[dict[str, str]],
    system_prompt: str,
    user_message: str,
    max_input_tokens: int,
    reserve_completion_tokens: int,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """
    请求模型前的历史整理：去空 → 去重用户长文 → 按 token 从最旧截断。
    返回 (prior, stats) 便于日志观测。
    """
    raw_len = len(history)
    no_empty = drop_empty_messages(history)
    cleaned = dedupe_repeated_user_messages(
        collapse_repeated_long_user_pastes(no_empty),
    )
    trimmed = trim_history_for_context(
        cleaned,
        system_prompt,
        user_message,
        max_input_tokens,
        reserve_completion_tokens,
    )
    stats = {
        "raw": raw_len,
        "after_empty": len(no_empty),
        "after_dedupe": len(cleaned),
        "after_trim": len(trimmed),
        "empty_dropped": raw_len - len(no_empty),
        "deduped": len(no_empty) - len(cleaned),
        "trimmed": len(cleaned) - len(trimmed),
    }
    return trimmed, stats


def estimate_prompt_tokens(
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
) -> int:
    """估算「system + 历史各条 content + 当前用户」拼接后的 token（与前端展示口径一致）。"""
    parts: list[str] = [system_prompt]
    for m in history:
        c = m.get("content")
        if c is not None and str(c).strip():
            parts.append(str(c))
    if user_message and str(user_message).strip():
        parts.append(str(user_message))
    blob = "\n\n".join(parts)
    return rough_token_estimate(blob)


def trim_history_for_context(
    history: list[dict[str, str]],
    system_prompt: str,
    user_message: str,
    max_input_tokens: int,
    reserve_completion_tokens: int,
) -> list[dict[str, str]]:
    """
    上下文过长时从**最旧**开始丢消息，直到估算 token 不超过预算。
    不改变磁盘上的完整历史，仅影响本次 API 请求携带的内容。
    """
    budget = max(512, int(max_input_tokens) - int(reserve_completion_tokens))
    trimmed = list(history)
    while trimmed:
        if estimate_prompt_tokens(system_prompt, trimmed, user_message) <= budget:
            break
        trimmed = trimmed[1:]
    return trimmed


def build_openai_messages(
    history: list[dict[str, str]],
    user_message: str,
    system_prompt: str,
) -> list[dict[str, str]]:
    """组装发给 Chat Completions 的 messages（含 system + 历史 + 当前用户）。"""
    msgs: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in history:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_message})
    return _normalize_messages(msgs)
