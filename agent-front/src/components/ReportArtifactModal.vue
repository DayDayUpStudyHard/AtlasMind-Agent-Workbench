<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="visible" class="artifact-modal-backdrop" @click.self="close" @keydown.escape="close">
        <div class="artifact-modal" role="dialog" aria-modal="true" :aria-labelledby="modalTitleId">
          <header class="artifact-modal-header">
            <div>
              <p class="section-kicker">{{ typeLabel }}</p>
              <h2 :id="modalTitleId">{{ report?.title || typeLabel }}</h2>
            </div>
            <button type="button" class="artifact-modal-close" aria-label="关闭" @click="close">&times;</button>
          </header>

          <div class="artifact-modal-meta" v-if="report">
            <span v-if="report.scoringVersion">{{ report.scoringVersion }}</span>
            <span v-if="report.analysisMode">{{ report.analysisMode }}</span>
            <span v-if="report.healthScore != null">{{ report.healthScore }}/100</span>
            <span>{{ formatDate(report.createTime) }}</span>
          </div>

          <div class="artifact-modal-body">
            <div v-if="report?.reportMarkdown" class="markdown-body" v-html="renderMarkdown(report.reportMarkdown)"></div>
            <div v-else-if="report?.summary" class="artifact-fallback">
              <p>{{ report.summary }}</p>
            </div>
            <div v-else class="blank-state">该报告暂无详细内容。</div>
          </div>

          <footer class="artifact-modal-footer">
            <button type="button" class="quiet-button" @click="close">关闭</button>
            <button type="button" class="primary-button" @click="downloadArtifact" :disabled="!report?.reportMarkdown">
              导出 Markdown
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  visible: { type: Boolean, default: false },
  report: { type: Object, default: null },
  taskType: { type: String, default: 'HEALTH_ANALYSIS' }
})

const emit = defineEmits(['close'])

const typeLabel = computed(() => {
  return {
    HEALTH_ANALYSIS: '项目健康分析',
    HEALTH_REPORT: '项目健康分析',
    PROJECT_ONBOARDING: '项目接手手册',
    ONBOARDING_GUIDE: '项目接手手册',
    ENGINEERING_DECISION: '研发决策备忘录',
    DECISION_MEMO: '研发决策备忘录'
  }[props.taskType] || '任务产物'
})

const modalTitleId = 'artifact-modal-title'

function close() {
  emit('close')
}

function renderMarkdown(value) {
  return marked.parse(value || '', { breaks: true })
}

function formatDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : ''
}

function downloadArtifact() {
  const markdown = props.report?.reportMarkdown
  if (!markdown) return
  const typeSuffix = {
    HEALTH_ANALYSIS: '健康分析报告',
    HEALTH_REPORT: '健康分析报告',
    PROJECT_ONBOARDING: '项目接手手册',
    ONBOARDING_GUIDE: '项目接手手册',
    ENGINEERING_DECISION: '研发决策备忘录',
    DECISION_MEMO: '研发决策备忘录'
  }[props.taskType] || '任务产物'
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${typeSuffix}.md`
  link.click()
  URL.revokeObjectURL(link.href)
}

function onKeydown(event) {
  if (event.key === 'Escape' && props.visible) close()
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  if (props.visible) document.body.style.overflow = 'hidden'
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})

watch(() => props.visible, (value) => {
  document.body.style.overflow = value ? 'hidden' : ''
})
</script>

<style scoped>
.artifact-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 500;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 48px 24px 60px;
  background: rgba(15, 23, 42, 0.48);
  overflow-y: auto;
}

.artifact-modal {
  width: min(820px, 100%);
  max-height: none;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-top: 4px solid var(--atlas-primary);
  border-radius: 4px;
  box-shadow: 0 22px 48px rgba(15, 23, 42, 0.22);
  display: flex;
  flex-direction: column;
}

.artifact-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px 0;
}

.artifact-modal-header h2 {
  margin: 4px 0 0;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 26px;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.artifact-modal-close {
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  background: var(--atlas-surface);
  color: var(--atlas-muted);
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}

.artifact-modal-close:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.artifact-modal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--atlas-border);
}

.artifact-modal-meta span {
  padding: 4px 8px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 3px;
  font-size: 11px;
  font-weight: 800;
}

.artifact-modal-body {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
}

.artifact-modal-body .markdown-body {
  font-size: 15px;
  line-height: 1.85;
}

.artifact-fallback p {
  color: var(--atlas-muted);
  font-size: 14px;
  line-height: 1.7;
}

.artifact-modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--atlas-border);
}

.quiet-button,
.primary-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 4px;
  border: 1px solid var(--atlas-border);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
  text-decoration: none;
  white-space: nowrap;
}

.quiet-button {
  color: var(--atlas-muted);
  background: var(--atlas-surface);
}

.quiet-button:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.primary-button {
  color: #fff;
  background: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.primary-button:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

.blank-state {
  padding: 22px 0 5px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
}

/* Transition */
.modal-enter-active {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-leave-active {
  transition: all 0.15s ease;
}

.modal-enter-from {
  opacity: 0;
}

.modal-enter-from .artifact-modal {
  transform: translateY(24px) scale(0.97);
  opacity: 0;
}

.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .artifact-modal {
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-leave-active .artifact-modal {
  transition: all 0.15s ease;
}

@media (max-width: 620px) {
  .artifact-modal-backdrop {
    padding: 16px 8px 40px;
  }

  .artifact-modal-header h2 {
    font-size: 21px;
  }

  .artifact-modal-body {
    padding: 16px;
  }
}
</style>
