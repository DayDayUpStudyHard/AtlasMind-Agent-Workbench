<template>
  <article
    class="task-card"
    :class="[
      definition.tone,
      {
        'has-report': !!latestReport,
        'is-running': isRunning,
        'is-expanded': expanded && hasContent
      }
    ]"
    @mouseenter="showTooltip = !!latestReport"
    @mouseleave="showTooltip = false"
  >
    <!-- Running progress bar -->
    <div v-if="isRunning" class="task-running-bar">
      <i :style="{ width: `${latestRun?.progress || 0}%` }"></i>
    </div>

    <div class="task-topline">
      <span>{{ definition.eyebrow }}</span>
      <small v-if="isRunning">{{ runProgressLabel(latestRun) }}</small>
      <small v-else-if="latestReport">{{ statusSummary }}</small>
      <small v-else>尚未运行</small>
    </div>

    <h3>{{ definition.title }}</h3>
    <p>{{ definition.description }}</p>

    <!-- Result preview (shown when report exists and not running) -->
    <div v-if="latestReport && !isRunning" class="task-result-preview">
      <span class="result-chip" v-if="latestReport.healthStatus">{{ healthLabel(latestReport.healthStatus) }}</span>
      <span class="result-chip" v-if="latestReport.healthScore != null">{{ latestReport.healthScore }}/100</span>
      <span class="result-chip">{{ reportTypeLabel(latestReport.reportType || definition.type) }}</span>
    </div>

    <div class="task-output">产物：{{ definition.output }}</div>

    <div class="task-actions">
      <button
        v-if="isRunning"
        type="button"
        class="task-action running-action"
        disabled
      >
        {{ latestRun?.currentStep || '运行中...' }}
      </button>
      <button
        v-else-if="latestReport"
        type="button"
        class="task-action view-action"
        @click="$emit('viewReport', latestReport)"
      >
        查看报告
      </button>
      <button
        v-if="hasContent && !isRunning"
        type="button"
        class="task-action expand-action"
        @click="$emit('toggle')"
      >
        {{ expanded ? '收起详情' : '展开详情' }}
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ rotated: expanded }">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>
      <button
        type="button"
        class="task-action"
        :class="latestReport ? 'quiet-action' : 'launch-action'"
        :disabled="running"
        @click="$emit('launch', definition.type)"
      >
        {{ latestReport ? '重新运行' : definition.action }}
      </button>
    </div>

    <!-- Hover tooltip preview -->
    <transition name="tooltip">
      <div v-if="showTooltip && latestReport && !isRunning && !expanded" class="task-tooltip">
        <strong>{{ latestReport.title || definition.title }}</strong>
        <p>{{ previewText }}</p>
        <small>点击"展开详情"查看完整内容</small>
      </div>
    </transition>

    <!-- Expandable content slot -->
    <transition name="expand">
      <div v-if="expanded && hasContent" class="task-card-content">
        <slot name="content" />
      </div>
    </transition>
  </article>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  definition: { type: Object, required: true },
  latestRun: { type: Object, default: null },
  running: { type: Boolean, default: false },
  expanded: { type: Boolean, default: false }
})

defineEmits(['launch', 'viewReport', 'toggle'])

const showTooltip = ref(false)

const isRunning = computed(() => {
  const status = props.latestRun?.status
  // LIMITED is terminal — a scoped report was delivered, not a running task.
  return status && !['COMPLETED', 'FAILED', 'WAITING_APPROVAL', 'LIMITED'].includes(status)
})

const latestReport = computed(() => {
  return props.latestRun?.report || null
})

const hasContent = computed(() => {
  return !!latestReport.value
})

const statusSummary = computed(() => {
  if (!latestReport.value) return ''
  if (latestReport.value.healthScore != null) {
    return `${latestReport.value.healthScore}/100 ${healthLabel(latestReport.value.healthStatus)}`
  }
  return reportTypeLabel(latestReport.value.reportType || props.definition.type)
})

const previewText = computed(() => {
  const report = latestReport.value
  if (!report) return '暂无内容'
  const summary = report.summary || ''
  const snippet = summary.length > 140 ? summary.slice(0, 140) + '...' : summary
  return snippet || '点击展开详情查看完整报告'
})

function runProgressLabel(run) {
  const status = String(run?.status || '')
  if (status === 'CREATED') return '排队中'
  if (status === 'WAITING_APPROVAL') return '待审批'
  if (status === 'COMPLETED') return '100%'
  if (status === 'FAILED') return '失败'
  return `${run?.progress || 0}%`
}

function healthLabel(status) {
  return { HEALTHY: '稳定', WATCH: '关注', AT_RISK: '有风险', UNKNOWN: '未分析' }[status] || status || ''
}

function reportTypeLabel(type) {
  return {
    HEALTH_REPORT: '健康报告',
    ONBOARDING_GUIDE: '接手手册',
    DECISION_MEMO: '决策备忘录'
  }[type] || type || ''
}
</script>

<style scoped>
.task-card {
  position: relative;
  min-width: 0;
  padding: 19px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  overflow: visible;
  transition: border-color 0.2s;
}

.task-card.has-report {
  border-left: 3px solid var(--atlas-primary);
}

.task-card.is-running {
  border-left: 3px solid var(--atlas-warning);
}

.task-card.is-expanded {
  border-color: var(--atlas-primary);
  border-left: 3px solid var(--atlas-primary);
  box-shadow: 0 2px 12px rgba(31, 45, 61, 0.06);
}

.task-running-bar {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--atlas-border);
}

.task-running-bar i {
  display: block;
  height: 100%;
  background: var(--atlas-warning);
  transition: width 0.6s ease;
  animation: pulse-bar 2s ease-in-out infinite;
}

@keyframes pulse-bar {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

.task-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.task-topline > span {
  color: var(--atlas-primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
}

.task-topline > small {
  color: var(--atlas-subtle);
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}

h3 {
  margin: 8px 0 0;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 21px;
  line-height: 1.3;
}

p {
  margin: 6px 0 0;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.55;
}

.task-result-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.result-chip {
  padding: 4px 7px;
  border: 1px solid var(--atlas-border);
  border-radius: 3px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  font-size: 11px;
  font-weight: 800;
}

.task-output {
  margin-top: 10px;
  color: var(--atlas-subtle);
  font-size: 11px;
}

.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: auto;
  padding-top: 14px;
}

.task-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 36px;
  padding: 0 12px;
  border-radius: 4px;
  border: 1px solid var(--atlas-border);
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.launch-action {
  color: #fff;
  background: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.launch-action:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

.view-action {
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-primary);
}

.view-action:hover {
  color: #fff;
  background: var(--atlas-primary);
}

.expand-action {
  color: var(--atlas-muted);
  background: var(--atlas-bg);
  border-color: var(--atlas-border);
}

.expand-action:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.expand-action svg {
  transition: transform 0.2s;
}

.expand-action svg.rotated {
  transform: rotate(180deg);
}

.quiet-action {
  color: var(--atlas-muted);
  background: var(--atlas-surface);
}

.quiet-action:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.running-action {
  color: var(--atlas-warning);
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-warning);
  cursor: not-allowed;
}

button:disabled {
  cursor: not-allowed;
  opacity: .55;
}

/* Hover tooltip */
.task-tooltip {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 10;
  padding: 12px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border-strong);
  border-radius: 4px;
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.18);
}

.task-tooltip strong {
  display: block;
  color: var(--atlas-text);
  font-size: 13px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.task-tooltip p {
  margin: 6px 0;
  color: var(--atlas-muted);
  font-size: 12px;
  line-height: 1.55;
}

.task-tooltip small {
  color: var(--atlas-subtle);
  font-size: 10px;
}

.tooltip-enter-active {
  transition: all 0.15s ease;
}

.tooltip-leave-active {
  transition: all 0.1s ease;
}

.tooltip-enter-from,
.tooltip-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* Expandable content area */
.task-card-content {
  margin: 18px -19px -19px;
  padding: 0;
  border-top: 2px solid var(--atlas-primary);
  background: var(--atlas-bg);
}

.expand-enter-active {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 3000px;
  opacity: 1;
}
</style>
