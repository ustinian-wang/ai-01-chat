from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """与 langchain-test 一致的聊天请求体。"""

    thread_id: str = Field(..., description="会话 ID，用于维护上下文")
    message: str = Field(..., description="用户文本消息")
    image_url: str = Field(default="", description="图片 URL，可为空；本示例仅作上下文说明不入模")
    provider: str = Field(
        default="",
        description="LLM 提供商 id，如 spark-lite、sub2api；空则使用 DEFAULT_PROVIDER",
    )
    model: str = Field(
        default="",
        description="模型 id，覆盖该提供商默认模型；空则使用 PROVIDER_*_MODEL",
    )


class SessionCreateRequest(BaseModel):
    """创建空会话；不传 thread_id 时由服务端生成 UUID。"""

    thread_id: str | None = Field(default=None, description="可选，自定义会话 ID；留空则自动生成")
