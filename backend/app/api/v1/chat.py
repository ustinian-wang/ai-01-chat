from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, SessionCreateRequest
from app.services import llm_providers, message_store
from app.services.openai_stream import sse_chat_stream

router = APIRouter()


@router.get("/chat/providers")
async def list_chat_providers():
    """列出已配置的模型网关（不含密钥），供前端切换。"""
    return llm_providers.providers_for_api()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """与 langchain-test 相同路径；本服务为 token 级 SSE。"""
    provider = (request.provider or "").strip() or None
    model = (request.model or "").strip() or None
    return StreamingResponse(
        sse_chat_stream(request.thread_id, request.message, request.image_url, provider, model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/sessions")
async def list_chat_sessions():
    """列出本地持久化的会话（按最近修改倒序），供左侧会话栏使用。"""
    sessions = await message_store.list_sessions()
    return {"sessions": sessions}


@router.post("/chat/sessions")
async def create_chat_session(body: SessionCreateRequest = SessionCreateRequest()):
    """创建空会话文件；便于前端「新对话」立即出现在列表中。"""
    raw = (body.thread_id or "").strip()
    tid = raw or str(uuid4())
    await message_store.ensure_session(tid)
    return {"thread_id": tid}


@router.get("/chat/messages")
async def get_chat_messages(thread_id: str):
    messages = await message_store.get_thread_messages(thread_id)
    return {"messages": messages}


@router.delete("/chat/messages")
async def clear_chat_messages(thread_id: str):
    await message_store.clear_thread(thread_id)
    return {"success": True}
