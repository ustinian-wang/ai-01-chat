<template>
  <div class="app-shell">
    <aside class="sidebar" aria-label="会话列表">
      <div class="sidebar-head">
        <button type="button" class="btn primary sidebar-new" :disabled="busy" @click="createNewSession">
          + 新对话
        </button>
      </div>
      <div class="sidebar-list">
        <div
          v-for="s in sessions"
          :key="s.thread_id"
          class="session-row"
          :class="{ active: s.thread_id === threadId }"
        >
          <button type="button" class="session-item" :disabled="busy" @click="selectSession(s.thread_id)">
            <span class="session-title">{{ s.title || '新对话' }}</span>
            <span class="session-meta">{{ s.message_count }}</span>
          </button>
          <button
            type="button"
            class="session-del"
            title="删除会话"
            :disabled="busy"
            @click="deleteSession(s.thread_id)"
          >
            ×
          </button>
        </div>
      </div>
    </aside>

    <div class="main-column">
      <div class="layout">
        <header class="header">
          <div class="header-main">
            <div>
              <h1 class="title">ai-01-chat</h1>
              <p class="subtitle">
                Vue · Markdown · SSE 流式 · 左侧切换会话
                <template v-if="activeProvider && selectedModel">
                  · {{ activeProvider.label }} / {{ selectedModel }}
                </template>
              </p>
              <p class="session-active-label">当前：{{ activeTitle }}</p>
            </div>
            <div class="toolbar">
              <label v-if="providers.length" class="provider-picker">
                <span class="provider-picker-label">接口</span>
                <select
                  v-model="selectedProvider"
                  class="provider-select"
                  :disabled="busy"
                  @change="onProviderChange"
                >
                  <option v-for="p in providers" :key="p.id" :value="p.id">
                    {{ p.label }}
                  </option>
                </select>
              </label>
              <label v-if="modelOptions.length" class="provider-picker">
                <span class="provider-picker-label">模型</span>
                <select
                  v-model="selectedModel"
                  class="provider-select"
                  :disabled="busy"
                  @change="onModelChange"
                >
                  <option v-for="m in modelOptions" :key="m" :value="m">
                    {{ m }}
                  </option>
                </select>
              </label>
              <button type="button" class="btn ghost" :disabled="busy" @click="loadHistory">刷新历史</button>
              <button type="button" class="btn danger" :disabled="busy" @click="clearHistory">删除当前会话</button>
            </div>
          </div>
          <ContextRing
            class="header-context"
            :used="contextUsage.tokenEstimate"
            :limit="contextUsage.limit"
            :ratio="contextUsage.ratio"
            :char-total="contextUsage.charTotal"
            :will-compact="contextUsage.willCompact"
            :max-limit="contextUsage.maxLimit"
            :reserve="contextUsage.reserve"
          />
        </header>

        <main ref="scrollRef" class="chat">
          <div v-if="!messages.length" class="empty">发一条消息开始对话；或点击「+ 新对话」创建会话。</div>
          <article
            v-for="m in messages"
            :key="m.id"
            class="msg"
            :class="m.role === 'user' ? 'msg-user' : 'msg-assistant'"
          >
            <div class="role">{{ m.role === 'user' ? '你' : '助手' }}</div>
            <div class="bubble md" v-html="renderMarkdown(m.content)" />
          </article>
        </main>

        <footer class="composer">
          <textarea
            v-model.trim="draft"
            class="input"
            rows="3"
            placeholder="输入消息，⌘+Enter 发送（Windows 为 Ctrl+Enter）；Enter 换行"
            :disabled="busy"
            @keydown="onKeydown"
          />
          <button type="button" class="btn primary" :disabled="busy || !draft" @click="send">发送</button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import ContextRing from './ContextRing.vue';
import { estimateApiContext } from './contextUsage.js';
import { renderMarkdown } from './markdown.js';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

const contextTokenLimit = Number(import.meta.env.VITE_CONTEXT_TOKEN_LIMIT || 8192);
const contextTokenReserve = Number(import.meta.env.VITE_CONTEXT_TOKEN_RESERVE || 1536);

const threadId = ref('');
const draft = ref('');
const messages = ref([]);
const busy = ref(false);
const scrollRef = ref(null);
const sessions = ref([]);
const providers = ref([]);
const selectedProvider = ref('');
const selectedModel = ref('');

const activeProvider = computed(() =>
  providers.value.find((p) => p.id === selectedProvider.value),
);

const modelOptions = computed(() => {
  const p = activeProvider.value;
  if (!p) return [];
  const list = Array.isArray(p.models) && p.models.length ? p.models : [p.model];
  return list.filter(Boolean);
});

function readModelMap() {
  try {
    const raw = window.localStorage.getItem('ai01_model_map');
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function writeModelMap(map) {
  window.localStorage.setItem('ai01_model_map', JSON.stringify(map));
}

function syncModelForProvider() {
  const p = activeProvider.value;
  if (!p) {
    selectedModel.value = '';
    return;
  }
  const options = modelOptions.value;
  const map = readModelMap();
  const saved = map[p.id];
  if (saved && options.includes(saved)) {
    selectedModel.value = saved;
  } else if (options.includes(p.model)) {
    selectedModel.value = p.model;
  } else {
    selectedModel.value = options[0] || p.model || '';
  }
}

const contextUsage = computed(() => {
  const est = estimateApiContext(messages.value, draft.value, {
    limit: contextTokenLimit,
    reserve: contextTokenReserve,
  });
  return {
    charTotal: est.charTotal,
    tokenEstimate: est.tokenEstimate,
    limit: est.budget,
    maxLimit: est.limit,
    reserve: est.reserve,
    ratio: est.ratio,
    willCompact: est.willCompact,
  };
});

const activeTitle = computed(() => {
  const cur = sessions.value.find((s) => s.thread_id === threadId.value);
  if (cur?.title) return cur.title;
  const firstUser = messages.value.find((m) => m.role === 'user');
  if (firstUser?.content) return String(firstUser.content).slice(0, 48);
  return '新对话';
});

function toApiUrl(path) {
  return `${API_BASE}${path}`;
}

function uid() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 生成 URL/文件名安全的会话 id（与后端持久化一致） */
function newThreadId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `local-${uid()}`;
}

function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  });
}

function parseSseDataLine(line) {
  const prefix = 'data: ';
  if (!line.startsWith(prefix)) return null;
  try {
    return JSON.parse(line.slice(prefix.length));
  } catch {
    return null;
  }
}

async function consumeStream(response, onPayload) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const block of chunks) {
      for (const rawLine of block.split('\n')) {
        const line = rawLine.trim();
        if (!line) continue;
        const payload = parseSseDataLine(line);
        if (payload) await onPayload(payload);
      }
    }
  }
  if (buffer.trim()) {
    for (const rawLine of buffer.split('\n')) {
      const line = rawLine.trim();
      if (!line) continue;
      const payload = parseSseDataLine(line);
      if (payload) await onPayload(payload);
    }
  }
}

async function loadProviders() {
  try {
    const res = await fetch(toApiUrl('/api/v1/chat/providers'));
    const data = await res.json();
    const list = Array.isArray(data.providers) ? data.providers : [];
    providers.value = list;
    const saved = window.localStorage.getItem('ai01_provider') || '';
    const defaultId = data.default_provider || list[0]?.id || '';
    if (saved && list.some((p) => p.id === saved)) {
      selectedProvider.value = saved;
    } else {
      selectedProvider.value = defaultId;
    }
    syncModelForProvider();
  } catch {
    providers.value = [];
    selectedProvider.value = '';
    selectedModel.value = '';
  }
}

function onProviderChange() {
  window.localStorage.setItem('ai01_provider', selectedProvider.value);
  syncModelForProvider();
}

function onModelChange() {
  const map = readModelMap();
  map[selectedProvider.value] = selectedModel.value;
  writeModelMap(map);
}

async function loadSessions() {
  try {
    const res = await fetch(toApiUrl('/api/v1/chat/sessions'));
    const data = await res.json();
    sessions.value = Array.isArray(data.sessions) ? data.sessions : [];
  } catch {
    sessions.value = [];
  }
}

async function createNewSession() {
  if (busy.value) return;
  const id = newThreadId();
  busy.value = true;
  try {
    const res = await fetch(toApiUrl('/api/v1/chat/sessions'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thread_id: id }),
    });
    const raw = await res.text().catch(() => '');
    if (!res.ok) throw new Error(raw || `HTTP ${res.status}`);
    let data = {};
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = {};
    }
    threadId.value = data.thread_id || id;
    messages.value = [];
    await loadSessions();
  } catch (e) {
    messages.value = [{ id: uid(), role: 'assistant', content: `创建会话失败：${e}` }];
  } finally {
    busy.value = false;
    scrollToBottom();
  }
}

async function selectSession(tid) {
  if (!tid || busy.value || tid === threadId.value) return;
  threadId.value = tid;
  await loadHistory();
}

async function deleteSession(tid) {
  if (!tid || busy.value) return;
  busy.value = true;
  try {
    await fetch(toApiUrl(`/api/v1/chat/messages?thread_id=${encodeURIComponent(tid)}`), {
      method: 'DELETE',
    });
    await loadSessions();
    if (threadId.value === tid) {
      messages.value = [];
      if (sessions.value.length) {
        threadId.value = sessions.value[0].thread_id;
        await loadHistory();
      } else {
        await createNewSession();
      }
    }
  } catch (e) {
    messages.value.push({ id: uid(), role: 'assistant', content: `删除失败：${e}` });
  } finally {
    busy.value = false;
  }
}

async function send() {
  const text = draft.value;
  if (!text || busy.value) return;
  if (!threadId.value) {
    await createNewSession();
    if (!threadId.value) return;
  }

  busy.value = true;
  messages.value.push({ id: uid(), role: 'user', content: text });
  const assistantId = uid();
  messages.value.push({ id: assistantId, role: 'assistant', content: '' });
  draft.value = '';
  scrollToBottom();

  const res = await fetch(toApiUrl('/api/v1/chat/stream'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      thread_id: threadId.value,
      message: text,
      image_url: '',
      provider: selectedProvider.value,
      model: selectedModel.value,
    }),
  });

  if (!res.ok || !res.body) {
    const t = await res.text().catch(() => '');
    patchAssistant(assistantId, `请求失败：HTTP ${res.status} ${t}`);
    busy.value = false;
    await loadSessions();
    return;
  }

  await consumeStream(res, async (payload) => {
    if (payload.delta) {
      const cur = messages.value.find((m) => m.id === assistantId);
      if (cur) cur.content += payload.delta;
      scrollToBottom();
    }
    if (payload.error) {
      patchAssistant(assistantId, `错误：${payload.error}`);
    }
  });

  busy.value = false;
  scrollToBottom();
  await loadSessions();
}

function patchAssistant(id, content) {
  const cur = messages.value.find((m) => m.id === id);
  if (cur) cur.content = content;
}

async function loadHistory() {
  if (!threadId.value) return;
  busy.value = true;
  try {
    const res = await fetch(
      toApiUrl(`/api/v1/chat/messages?thread_id=${encodeURIComponent(threadId.value)}`),
    );
    const data = await res.json();
    const list = Array.isArray(data.messages) ? data.messages : [];
    messages.value = list.map((m) => ({
      id: uid(),
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: String(m.content ?? ''),
    }));
  } catch (e) {
    messages.value = [{ id: uid(), role: 'assistant', content: `加载历史失败：${e}` }];
  } finally {
    busy.value = false;
    scrollToBottom();
  }
}

async function clearHistory() {
  if (!threadId.value) return;
  const prev = threadId.value;
  busy.value = true;
  try {
    await fetch(toApiUrl(`/api/v1/chat/messages?thread_id=${encodeURIComponent(prev)}`), {
      method: 'DELETE',
    });
    messages.value = [];
    await loadSessions();
    if (sessions.value.length) {
      const next = sessions.value.find((s) => s.thread_id !== prev) || sessions.value[0];
      threadId.value = next.thread_id;
      await loadHistory();
    } else {
      await createNewSession();
    }
  } catch (e) {
    messages.value.push({ id: uid(), role: 'assistant', content: `删除失败：${e}` });
  } finally {
    busy.value = false;
  }
}

function onKeydown(e) {
  const sendShortcut = e.key === 'Enter' && (e.metaKey || e.ctrlKey);
  if (sendShortcut) {
    e.preventDefault();
    send();
  }
}

onMounted(async () => {
  await loadProviders();
  await loadSessions();
  const saved = window.localStorage.getItem('ai01_thread_id');
  if (saved && sessions.value.some((s) => s.thread_id === saved)) {
    threadId.value = saved;
  } else if (saved) {
    threadId.value = saved;
  } else if (sessions.value.length) {
    threadId.value = sessions.value[0].thread_id;
  } else {
    await createNewSession();
    return;
  }
  await loadHistory();
  await loadSessions();
});

watch(threadId, (v) => {
  window.localStorage.setItem('ai01_thread_id', v);
});
</script>
