"""OpenAI SDK 流式 Chat Completions + SSE 封装。

讯飞星火 HTTP 兼容调用说明见官方文档：
https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html
鉴权：Authorization: Bearer 可为（1）控制台 HTTP 的 APIPassword，或（2）APIKey:APISecret 拼接（与官方 OpenAI SDK 示例一致）。
兼容 SDK 时 base_url 为 .../v1/；模型取值如 lite、generalv3.5、4.0Ultra 等与文档表格一致。
"""

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.services import message_store

# backend/.env（与 app/main.py 中 load 路径一致）
_DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"

SYSTEM_PROMPT = """你是一个 helpful 的编程与通识助手。回答尽量使用 Markdown；涉及代码时请使用带语言标记的 fenced code block（例如 ```python）。保持简洁准确。"""


def _normalize_base_url(url: str | None) -> str | None:
    """与讯飞文档一致：兼容 OpenAI SDK 时 base_url 建议以 / 结尾。"""
    if not url:
        return None
    u = url.strip().rstrip("/")
    return f"{u}/"


def _client() -> AsyncOpenAI:
    # 每次请求前再读一次 .env，避免 uvicorn 长驻进程未重启时仍用旧环境
    if _DOTENV_PATH.is_file():
        # 本地开发以 backend/.env 为准，避免 shell 里空变量盖住文件
        load_dotenv(_DOTENV_PATH, override=True)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")
    raw_base = os.getenv("OPENAI_BASE_URL", "").strip()
    base_url = _normalize_base_url(raw_base if raw_base else None)
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


def _model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def _xfyun_auth_hint(err: BaseException) -> str:
    """针对讯飞 HTTP 常见误配给出可操作建议。"""
    raw = os.getenv("OPENAI_BASE_URL", "").lower()
    if "xf-yun" not in raw and "xfyun" not in raw:
        return ""
    msg = str(err).lower()
    if "401" not in msg and "apikey" not in msg and "hmac" not in msg:
        return ""
    key = os.getenv("OPENAI_API_KEY", "")
    if ":" in key:
        return (
            " 讯飞侧说明（401）：请核对 APIKey:APISecret 与当前 OPENAI_MODEL、控制台开通的 HTTP 产品一致；"
            "或改用控制台「HTTP 服务接口认证」的 APIPassword；修改 backend/.env 后若仍失败请重启 uvicorn。"
        )
    return (
        " 讯飞侧说明（401）：请检查 OPENAI_API_KEY（APIPassword 或 APIKey:APISecret）与 base_url、model；"
        "修改 backend/.env 后请重启 uvicorn。"
    )


async def sse_chat_stream(
    thread_id: str,
    message: str,
    image_url: str = "",
) -> AsyncIterator[str]:
    """
    产出 text/event-stream 片段。
    事件格式：data: {"delta":"..."} 逐字；结束时 data: {"done":true}。
    错误：data: {"error":"..."}。
    """
    user_display = message
    if image_url.strip():
        user_display = f"{message}\n\n（附图链接，当前演示未做多模态入参：{image_url.strip()}）"

    try:
        history = await message_store.get_thread_messages(thread_id)
        # 发给模型的历史不含本轮用户（由 build_openai_messages 追加）
        prior = list(history)

        # 上下文过长：按预算从旧到新截断（磁盘仍保留全量）
        try:
            limit_raw = os.getenv("CONTEXT_TOKEN_LIMIT", "8192").strip()
            max_in = int(limit_raw) if limit_raw else 8192
        except ValueError:
            max_in = 8192
        try:
            res_raw = os.getenv("CONTEXT_TOKEN_RESERVE", "1536").strip()
            reserve = int(res_raw) if res_raw else 1536
        except ValueError:
            reserve = 1536
        if max_in < 1024:
            max_in = 1024
        prior = message_store.trim_history_for_context(
            prior,
            SYSTEM_PROMPT,
            user_display,
            max_input_tokens=max_in,
            reserve_completion_tokens=reserve,
        )

        messages = message_store.build_openai_messages(prior, user_display, SYSTEM_PROMPT)
        client = _client()
        stream = await client.chat.completions.create(
            model=_model(),
            messages=messages,
            stream=True,
            # 讯飞文档可选参数 user：用户唯一 id；此处用 thread_id 便于会话关联
            user=thread_id,
        )

        full_assistant = ""
        async for event in stream:
            choice = event.choices[0] if event.choices else None
            if not choice:
                continue
            piece = choice.delta.content or ""
            if piece:
                full_assistant += piece
                yield f"data: {json.dumps({'delta': piece}, ensure_ascii=False)}\n\n"

        await message_store.append_exchange(thread_id, user_display, full_assistant)
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    except Exception as err:  # noqa: BLE001 — 演示项目统一返回 SSE 错误帧
        detail = str(err) + _xfyun_auth_hint(err)
        yield f"data: {json.dumps({'error': detail}, ensure_ascii=False)}\n\n"
