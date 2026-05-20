/**
 * 与 backend/app/services/openai_stream.py 中 SYSTEM_PROMPT 保持字面一致，仅用于前端 token 估算展示。
 */
export const SYSTEM_PROMPT_FOR_ESTIMATE =
  '你是一个 helpful 的编程与通识助手。回答尽量使用 Markdown；涉及代码时请使用带语言标记的 fenced code block（例如 ```python）。保持简洁准确。';

/**
 * 粗略 token 估算：参考讯飞文档「1 token ≈ 1.5 汉字」；ASCII 等按更小权重。
 */
export function roughTokenEstimate(text) {
  if (!text) {
    return 0;
  }
  let t = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    // CJK 统一表意 + 扩展 A 常见段（简化）
    if ((c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3400 && c <= 0x4dbf)) {
      t += 1 / 1.5;
    } else if (/\s/.test(text[i])) {
      t += 0.08;
    } else {
      t += 0.28;
    }
  }
  return Math.max(0, Math.round(t));
}

/** 与后端 drop_empty_messages 一致 */
export function dropEmptyMessages(messages) {
  return messages.filter((m) => String(m?.content || '').trim());
}

const LONG_USER_MIN_CHARS = 600;
const LONG_USER_KEEP_COUNT = 1;

/** 多次相近长文粘贴：只保留最后一次超长用户消息（及紧随的 assistant） */
export function collapseRepeatedLongUserPastes(
  messages,
  minChars = LONG_USER_MIN_CHARS,
  keep = LONG_USER_KEEP_COUNT,
) {
  const longIndices = messages
    .map((m, i) => (m?.role === 'user' && String(m.content || '').length >= minChars ? i : -1))
    .filter((i) => i >= 0);
  if (longIndices.length <= keep) {
    return [...messages];
  }
  const dropIndices = new Set(longIndices.slice(0, longIndices.length - keep));
  const skip = new Set();
  dropIndices.forEach((i) => {
    skip.add(i);
    if (i + 1 < messages.length && messages[i + 1]?.role === 'assistant') {
      skip.add(i + 1);
    }
  });
  return messages.filter((_, i) => !skip.has(i));
}

/** 与后端 dedupe_repeated_user_messages 一致：相同用户正文只保留最后一次 */
export function dedupeRepeatedUserMessages(messages) {
  if (messages.length < 2) {
    return [...messages];
  }
  const lastIdxByContent = new Map();
  messages.forEach((m, i) => {
    if (m?.role !== 'user') {
      return;
    }
    const key = String(m.content || '').trim();
    if (key) {
      lastIdxByContent.set(key, i);
    }
  });
  const skip = new Set();
  messages.forEach((m, i) => {
    if (m?.role !== 'user') {
      return;
    }
    const key = String(m.content || '').trim();
    if (!key || lastIdxByContent.get(key) === i) {
      return;
    }
    skip.add(i);
    if (i + 1 < messages.length && messages[i + 1]?.role === 'assistant') {
      skip.add(i + 1);
    }
  });
  return messages.filter((_, i) => !skip.has(i));
}

function blobFromParts(parts) {
  const blob = parts.join('\n\n');
  return {
    charTotal: blob.length,
    tokenEstimate: roughTokenEstimate(blob),
  };
}

/**
 * 估算「下一次请求」送入模型的上下文（与后端 prepare_history_for_api 口径对齐）。
 */
export function estimateApiContext(messages, draft, options = {}) {
  const limit = options.limit > 0 ? options.limit : 8192;
  const reserve = options.reserve > 0 ? options.reserve : 1536;
  const budget = Math.max(512, limit - reserve);

  const rawLen = messages.length;
  const sanitized = dedupeRepeatedUserMessages(
    collapseRepeatedLongUserPastes(dropEmptyMessages(messages)),
  );
  const draftText = draft && String(draft).trim() ? String(draft) : '';

  let trimmed = [...sanitized];
  while (trimmed.length > 0) {
    const parts = [SYSTEM_PROMPT_FOR_ESTIMATE];
    for (const m of trimmed) {
      parts.push(String(m.content));
    }
    if (draftText) {
      parts.push(draftText);
    }
    if (roughTokenEstimate(parts.join('\n\n')) <= budget) {
      break;
    }
    trimmed = trimmed.slice(1);
  }

  const parts = [SYSTEM_PROMPT_FOR_ESTIMATE];
  for (const m of trimmed) {
    parts.push(String(m.content));
  }
  if (draftText) {
    parts.push(draftText);
  }
  const { charTotal, tokenEstimate } = blobFromParts(parts);

  return {
    charTotal,
    tokenEstimate,
    limit,
    reserve,
    budget,
    ratio: budget > 0 ? tokenEstimate / budget : 0,
    rawLen,
    sanitizedLen: sanitized.length,
    apiLen: trimmed.length,
    willCompact: rawLen > sanitized.length || sanitized.length > trimmed.length,
  };
}

/** @deprecated 使用 estimateApiContext；保留兼容 */
export function estimateFromMessages(messages, draft) {
  return estimateApiContext(messages, draft);
}
