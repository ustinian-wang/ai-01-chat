# ai-01-chat

教学向最小聊天示例：**OpenAI SDK + FastAPI SSE + 进程内对话上下文**，前端 **Vue 3 + Markdown + 代码高亮 + 流式展示**。

接口契约与 `projects/langchain-test` 对齐，便于对照学习：

- `POST /api/v1/chat/stream`：请求体 `{ thread_id, message, image_url? }`，响应 `text/event-stream`
- `GET /api/v1/chat/sessions`：列出本地会话（`sessions[].thread_id/title/updated_at/message_count`）
- `POST /api/v1/chat/sessions`：创建空会话；请求体可选 `{ thread_id? }`，不传则服务端生成 UUID
- `GET /api/v1/chat/messages?thread_id=...`
- `DELETE /api/v1/chat/messages?thread_id=...`

### `GET /chat/messages` 里为什么还是 `**`、没有像网页那样变粗？

**这是正常设计。** 该接口返回的是 **会话数据（JSON）**，每条里的 `content` 存的是模型产出的 **原文**（一般是 Markdown 源码），**不会在服务端转成 HTML**。原因包括：

- 与 **OpenAI / langchain-test** 一类接口习惯一致：历史是结构化消息，展示层（Web、App、CLI）各自决定如何渲染。
- **安全**：若接口直接返回 HTML，客户端 `innerHTML` 风险更大；Markdown 原文 + 前端 `marked` + `DOMPurify` 更易统一消毒。
- **curl / Postman** 看到的是 **传输层 JSON**，即「所见」为带星号的字符串；**浏览器里** Vue 用 `renderMarkdown(content)` 再 `v-html`，才是 **Markdown → HTML** 的「所得」。

若你希望在接口层就多返回一份 HTML，可自行扩展（例如增加 `content_html` 字段或 `?format=html`），本教学项目默认保持 **原文 JSON**，避免与前端解析逻辑重复。

与 `langchain-test` 的差异（刻意设计）：

- 本项目的 `/chat/stream` 为 **token 级 SSE**（`data: {"delta":"..."}`），前端用 `fetch` + `ReadableStream` 解析
- 后端使用 **官方 `openai` Python SDK** 的 `chat.completions.create(..., stream=True)`
- 会话历史：**内存 + 本地文件** 持久化到 `backend/data/sessions/<thread_id 安全化>.json`（UTF-8 JSON 对象：`thread_id`、`title`、`updated_at`、`messages`；兼容旧版「纯数组」文件），**重启后端仍可拉历史**；不做登录/多租户（默认单用户，仅用 `thread_id` 区分会话）；前端左侧栏调用 `GET/POST /chat/sessions` 管理会话列表
- **上下文过长**：`POST /chat/stream` 组装请求前会按 `CONTEXT_TOKEN_LIMIT` / `CONTEXT_TOKEN_RESERVE` 用与前端一致的粗略估算做截断，**从最旧消息起丢弃**直到落入预算；**不删磁盘历史**，仅当次请求变短

## 环境变量

复制 `/.env.example` 为 `/.env`（或直接在 `backend/.env` 配置），至少需要：

```env
OPENAI_API_KEY=...
# 可选：兼容 OpenAI 的第三方网关（如 DashScope 兼容模式）
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini
BACKEND_PORT=8002
# 可选：调用模型前对「system + 历史 + 当前用户」做粗略 token 预算（与前端 contextUsage 同口径）
# 超出则从最旧消息开始丢弃，磁盘 JSON 仍保留全量；建议与前端 VITE_CONTEXT_TOKEN_LIMIT 对齐
CONTEXT_TOKEN_LIMIT=8192
# 为模型回复预留的 token 预算（从 CONTEXT_TOKEN_LIMIT 中扣除）
CONTEXT_TOKEN_RESERVE=1536
```

### 讯飞星火（HTTP / OpenAI 兼容）

官方说明：[星火认知大模型 HTTP 调用文档](https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html)。

- **请求地址**：`https://spark-api-open.xf-yun.com/v1/chat/completions`（由 SDK 根据 `base_url` 自动拼接，无需手写路径）。
- **兼容 OpenAI SDK 时的 `base_url`**：`https://spark-api-open.xf-yun.com/v1/`（建议带末尾 `/`；本项目在代码里也会规范化）。
- **鉴权**：`Authorization: Bearer <APIPassword>`，将控制台拿到的 **APIPassword** 填入 `OPENAI_API_KEY` 即可（若控制台给的是 `APPID:APISecret` 形式，以控制台「HTTP 服务接口认证」说明为准）。
- **`model`**：与文档表格一致，例如 Lite 用 `lite`，Max 用 `generalv3.5`，Ultra 用 `4.0Ultra` 等。
- **可选 `user`**：文档中的用户唯一 id；本项目在调用 SDK 时已传入 `user=thread_id`，便于按会话区分。

流式响应原始格式为 `data:{...}` 与 `data:[DONE]`（见文档）；经 OpenAI SDK 后仍按标准 `delta.content` 消费，无需前端改动。

### 常见问题：401 / `apikey not found` / HMAC 校验失败

星火 **HTTP（OpenAI 兼容）** 的 `Authorization: Bearer` 在官方文档与 SDK 示例中支持两种常见写法（以控制台当前产品说明为准）：

- **APIPassword**：控制台 **「HTTP 服务接口认证」** 中的单列字符串。
- **APIKey:APISecret**：`APIKey` 与 `APISecret` 用英文冒号拼接（与讯飞部分 OpenAI SDK 示例一致）；需与当前 `OPENAI_MODEL`、控制台开通的 **HTTP** 能力及 **同一应用** 对应。

若仍 401：请核对 **model 与密钥是否同属一个控制台产品**；修改 `backend/.env` 后 **重启 uvicorn**（或确保使用 `--reload` 已重载子进程）。本项目在创建 OpenAI 客户端前会再次 `load_dotenv(backend/.env)`，减少长驻进程读到旧环境的问题。

控制台：[讯飞开放平台](https://console.xfyun.cn/)

### 前端 Markdown：历史里 `**小标题：**` 不显粗体？

中文模型常写 **`**统一六国：**`**（全角冒号 `：` 贴在闭合 `**` 内侧）。CommonMark 下该写法**无法闭合粗体**，整段会像纯文本。前端已在 `frontend/src/markdown.js` 里对**代码块以外**的正文做轻量预处理（全角冒号外移、`:**` 后紧跟汉字时补空格），再交给 `marked` 解析；拉取历史与流式走的是同一套 `renderMarkdown`。

## 启动后端

```bash
cd projects/ai-01-chat/backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload
```

健康检查：`http://127.0.0.1:8002/health`

## 启动前端

```bash
cd projects/ai-01-chat/frontend
npm install
npm run dev
```

默认 `http://127.0.0.1:5174`，通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:8002`。

前端可在 `frontend/.env` 设置 **`VITE_CONTEXT_TOKEN_LIMIT`**（默认 `8192`），与当前星火版本「最大输入」对照，用于头部 **上下文用量圆环**（估算值，非官方 tokenizer）。

如需直连后端（不经代理），可使用：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8002 npm run dev
```

## SSE 事件格式

- 增量：`data: {"delta":"..."}\n\n`
- 结束：`data: {"done":true}\n\n`
- 异常：`data: {"error":"..."}\n\n`

## 你会接触到的概念

Chat Completions、messages 角色（system/user/assistant）、流式 chunks、thread 维度的 message history、Prompt（system）、Token（由模型与服务商计费，本项目不展示用量）。
