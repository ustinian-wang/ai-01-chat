<template>
  <div class="ctx-ring" :title="tip">
    <svg class="ctx-ring__svg" viewBox="0 0 44 44" aria-hidden="true">
      <circle class="ctx-ring__track" cx="22" cy="22" r="17" fill="none" stroke-width="3.2" />
      <circle
        class="ctx-ring__bar"
        :class="barClass"
        cx="22"
        cy="22"
        r="17"
        fill="none"
        stroke-width="3.2"
        stroke-linecap="round"
        :stroke-dasharray="dashArray"
        :stroke-dashoffset="dashOffset"
        transform="rotate(-90 22 22)"
      />
    </svg>
    <div class="ctx-ring__text">
      <span class="ctx-ring__pct">{{ pct }}%</span>
      <span class="ctx-ring__nums">≈{{ used }} / {{ limit }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  used: { type: Number, default: 0 },
  limit: { type: Number, default: 8192 },
  ratio: { type: Number, default: 0 },
  charTotal: { type: Number, default: 0 },
});

const r = 17;
const circumference = 2 * Math.PI * r;

const clamped = computed(() => Math.min(1, Math.max(0, props.ratio)));

const dashArray = computed(() => `${circumference} ${circumference}`);

const dashOffset = computed(() => circumference * (1 - clamped.value));

const pct = computed(() => Math.round(clamped.value * 1000) / 10);

const barClass = computed(() => {
  const x = clamped.value;
  if (x >= 1) return 'ctx-ring__bar--over';
  if (x >= 0.9) return 'ctx-ring__bar--warn';
  return 'ctx-ring__bar--ok';
});

const tip = computed(() => {
  return [
    '上下文用量（估算）',
    `约 ${props.used} tokens / 上限 ${props.limit}`,
    `字符约 ${props.charTotal}`,
    '含 system、当前消息与输入框草稿；与计费 tokenizer 不完全一致。',
  ].join('\n');
});
</script>

<style scoped>
.ctx-ring {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.ctx-ring__svg {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
}

.ctx-ring__track {
  stroke: #2a3140;
}

.ctx-ring__bar {
  transition: stroke-dashoffset 0.25s ease, stroke 0.2s ease;
}

.ctx-ring__bar--ok {
  stroke: #5b8cff;
}

.ctx-ring__bar--warn {
  stroke: #e6a23c;
}

.ctx-ring__bar--over {
  stroke: #ff6b6b;
}

.ctx-ring__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ctx-ring__pct {
  font-size: 14px;
  font-weight: 650;
  color: #e8ecf1;
  line-height: 1.1;
}

.ctx-ring__nums {
  font-size: 11px;
  color: #9aa3b2;
  white-space: nowrap;
}
</style>
