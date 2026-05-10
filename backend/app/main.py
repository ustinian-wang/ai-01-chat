import os
from pathlib import Path

from dotenv import load_dotenv

# 先于业务模块加载，确保 OPENAI_* 在 import openai_stream 前已注入
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.chat import router as chat_router

app = FastAPI(
    title="ai-01-chat",
    description="OpenAI SDK + SSE + 对话上下文（教学用最小实现）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/v1", tags=["chat"])


@app.get("/health")
async def health():
    return {"ok": True}


def _port() -> int:
    raw = os.getenv("BACKEND_PORT", "8002").strip()
    try:
        return int(raw)
    except ValueError:
        return 8002


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=_port(), reload=True)
