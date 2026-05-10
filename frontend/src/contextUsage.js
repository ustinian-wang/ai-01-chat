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

/**
 * 估算「下一次请求」大致会带上的上下文：system + 当前列表中有内容的消息 + 草稿。
 */
export function estimateFromMessages(messages, draft) {
  const parts = [SYSTEM_PROMPT_FOR_ESTIMATE];
  for (const m of messages) {
    const c = m?.content;
    if (c && String(c).length > 0) {
      parts.push(String(c));
    }
  }
  if (draft && String(draft).trim().length > 0) {
    parts.push(String(draft));
  }
  const blob = parts.join('\n\n');
  return {
    charTotal: blob.length,
    tokenEstimate: roughTokenEstimate(blob),
  };
}
