<template>
  <div class="workflow-next" :class="{ blocked: Boolean(blockedReason) }">
    <span class="workflow-next-kicker">下一步</span>
    <h4>{{ blockedReason ? blockedText : (nextAction.label || '暂无待办') }}</h4>
    <p v-if="blockedReason" class="workflow-next-reason">{{ blockedText }}</p>
    <p v-else-if="nextAction.actorRole" class="workflow-next-actor">
      {{ nextAction.actorRole }}<template v-if="nextAction.actorName"> · {{ nextAction.actorName }}</template>
    </p>
    <button
      v-if="showButton"
      type="button"
      class="primary-button workflow-next-button"
      :disabled="nextAction.enabled === false"
      @click="$emit('action', nextAction.type)"
    >
      {{ nextAction.label }}
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  nextAction: { type: Object, default: () => ({}) },
  blockedReason: { type: String, default: '' },
  summary: { type: String, default: '' },
})

defineEmits(['action'])

const blockedText = computed(() => props.summary || '当前阶段被阻塞，需要人工介入')

// 阻塞时仍可给出动作（如解析失败 → 重新上传）；只有 NONE 才隐藏按钮。
const showButton = computed(() =>
  Boolean(props.nextAction?.type) && props.nextAction.type !== 'NONE'
)
</script>

<style scoped>
.workflow-next {
  padding: 12px 14px;
  background: var(--atlas-surface, #fff);
  border: 1px solid var(--atlas-border, #e3e6ea);
  border-left: 3px solid var(--atlas-primary, #2f6feb);
  border-radius: 3px;
}
.workflow-next.blocked { border-left-color: #b35c56; background: #fffafa; }
.workflow-next-kicker {
  display: block;
  margin-bottom: 4px;
  color: var(--atlas-subtle, #7a848f);
  font-size: 9px;
  font-weight: 900;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.workflow-next h4 { margin: 0; color: var(--atlas-text, #1f2530); font-size: 13px; line-height: 1.45; }
.workflow-next-actor, .workflow-next-reason { margin: 5px 0 0; color: var(--atlas-muted, #5b6470); font-size: 11px; line-height: 1.5; }
.workflow-next.blocked h4, .workflow-next.blocked .workflow-next-reason { color: #8f3d38; }
.workflow-next-button { width: 100%; margin-top: 9px; justify-content: center; }
</style>
