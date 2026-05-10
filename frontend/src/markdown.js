import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import { Marked } from 'marked';
import { markedHighlight } from 'marked-highlight';

/** 显式同步解析，避免部分环境下 marked.parse 走异步返回非字符串 */
const mdParser = new Marked({ async: false, gfm: true, breaks: true });
mdParser.use(
  markedHighlight({
    emptyLangClass: 'hljs',
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(code, { language: lang }).value;
      }
      return hljs.highlightAuto(code).value;
    },
  }),
);

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * 大模型常见写法与 CommonMark 不完全兼容时的轻量修正（不处理 ``` 代码块内部）。
 *
 * 1) `**标题：**` 使用全角冒号 U+FF1A 且写在闭合 `**` 前时，marked 无法识别粗体 → 改为 `**标题**：`。
 * 2) `**标题:**汉字` 半角冒号后紧跟汉字时，闭合 `**` 不符合「右界」规则 → 在 `**` 与汉字间补空格（跳过含 `://` 的疑似 URL）。
 */
function preprocessModelMarkdown(src) {
  const parts = String(src).split(/(```[\s\S]*?```)/g);
  return parts
    .map((seg, i) => {
      if (i % 2 === 1) {
        return seg;
      }
      let t = seg;
      t = t.replace(/\*\*([^*]+?)\uFF1A\*\*/g, '**$1**：');
      t = t.replace(/\*\*([^*]+:[^*]*)\*\*([\u4e00-\u9fff])/g, (m, inner, cjk) => {
        if (String(inner).includes('://')) {
          return m;
        }
        return `**${inner}** ${cjk}`;
      });
      return t;
    })
    .join('');
}

/** marked 常见输出 + 代码高亮可能带 div/span.class */
const MD_ALLOWED_TAGS = [
  'p',
  'br',
  'strong',
  'em',
  'del',
  'ul',
  'ol',
  'li',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'blockquote',
  'code',
  'pre',
  'span',
  'div',
  'a',
  'img',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'colgroup',
  'col',
  'caption',
  'hr',
];

/**
 * 将 **Markdown 源码** 解析为 HTML，再经 DOMPurify 净化后供 v-html 使用。
 * 外层包 `.md-prose` 便于统一「富文本」排版样式。
 */
export function renderMarkdown(md) {
  const src = md == null ? '' : String(md);
  if (!src.trim()) {
    return '';
  }
  const normalized = preprocessModelMarkdown(src);
  let raw;
  try {
    raw = mdParser.parse(normalized);
  } catch (e) {
    raw = `<p class="md-parse-error">${escapeHtml(src)}</p>`;
  }
  if (typeof raw !== 'string') {
    raw = `<p class="md-parse-error">${escapeHtml(src)}</p>`;
  }
  const wrapped = `<div class="md-prose">${raw}</div>`;
  return DOMPurify.sanitize(wrapped, {
    ALLOWED_TAGS: MD_ALLOWED_TAGS,
    ALLOWED_ATTR: ['href', 'title', 'alt', 'src', 'class', 'target', 'rel', 'colspan', 'rowspan'],
  });
}
