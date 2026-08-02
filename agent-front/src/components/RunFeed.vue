<template>
  <div class="run-feed" :class="{ compact }">
    <div v-if="runs.length === 0" class="run-feed-empty">
      {{ emptyText }}
    </div>

    <div
      v-for="run in displayedRuns"
      :key="run.id"
      class="run-feed-row"
      :class="{
        'is-running': isActive(run.status),
        'is-completed': run.status === 'COMPLETED',
        'is-failed': run.status === 'FAILED',
        'just-finished': justFinishedIds.has(run.id)
      }"
      @click="navigateToRun(run)"
      role="button"
      tabindex="0"
      @keydown.enter="navigateToRun(run)"
    >
      <span class="run-feed-dot" :class="dotClass(run.status)"></span>

      <div class="run-feed-copy">
        <div class="run-feed-headline">
          <strong>{{ run.projectName || ('项目 #' + run.projectId) }}</strong>
          <span class="run-feed-type">{{ runTypeLabel(run.runType) }}</span>
        </div>
        <span class="run-feed-step">
          {{ run.currentStep || runStatusLabel(run.status) }}
          <template v-if="isActive(run.status)"> · {{ run.progress || 0 }}%</template>
        </span>
        <div v-if="isActive(run.status)" class="run-feed-progress">
          <i :style="{ width: `${run.progress || 0}%` }"></i>
        </div>
      </div>

      <div class="run-feed-right">
        <span class="run-feed-status" :class="dotClass(run.status)">{{ runStatusLabel(run.status) }}</span>
        <time>{{ relativeTime(run.createTime) }}</time>
      </div>
    </div>

    <div v-if="maxItems && runs.length > maxItems" class="run-feed-footer">
      <span>{{ remainingCount }} 条更多运行</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getRecentWorkspaceRuns } from '../api/index.js'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  maxItems: { type: Number, default: 8 },
  compact: { type: Boolean, default: false },
  polling: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无 Agent 运行记录' }
})

const emit = defineEmits(['statusChange'])
const router = useRouter()

const previousStatuses = ref({})
const justFinishedIds = ref(new Set())
let pollTimer = null

const displayedRuns = computed(() => {
  return props.runs.slice(0, props.maxItems)
})

const remainingCount = computed(() => {
  return Math.max(0, props.runs.length - props.maxItems)
})

// Polling
onMounted(() => {
  if (props.polling) {
    pollTimer = setInterval(refreshRuns, 8000)
  }
  trackStatuses(props.runs)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})

watch(() => props.runs, (next) => {
  detectStatusChanges(next)
  trackStatuses(next)
})

function trackStatuses(list) {
  const map = {}
  for (const run of list) {
    map[run.id] = run.status
  }
  previousStatuses.value = map
}

function detectStatusChanges(next) {
  for (const run of next) {
    const prev = previousStatuses.value[run.id]
    if (prev && prev !== run.status && isTerminal(run.status) && isActive(prev)) {
      // Run just completed or failed
      justFinishedIds.value = new Set([...justFinishedIds.value, run.id])
      emit('statusChange', { run, previousStatus: prev })
      setTimeout(() => {
        const updated = new Set(justFinishedIds.value)
        updated.delete(run.id)
        justFinishedIds.value = updated
      }, 4000)
    }
  }
}

async function refreshRuns() {
  try {
    const response = await getRecentWorkspaceRuns()
    const data = response.data.data || []
    detectStatusChanges(data)
    trackStatuses(data)
  } catch {
    // silent fail on poll
  }
}

function navigateToRun(run) {
  if (run.projectId) {
    router.push({ path: `/contracts/${run.subjectId || run.projectId}`, query: { runId: String(run.id) } })
  }
}

function isActive(status) {
  return status && !['COMPLETED', 'FAILED', 'WAITING_APPROVAL'].includes(status)
}

function isTerminal(status) {
  return ['COMPLETED', 'FAILED'].includes(status)
}

function dotClass(status) {
  const normalized = String(status || '').toLowerCase()
  if (['completed', 'done'].includes(normalized)) return 'ok'
  if (['failed', 'error'].includes(normalized)) return 'error'
  if (['created', 'context_building', 'analyzing', 'verifying', 'planning'].includes(normalized)) return 'active'
  if (normalized === 'waiting_approval') return 'waiting'
  return 'unknown'
}

function runTypeLabel(type) {
  return {
    HEALTH_ANALYSIS: '健康分析',
    PROJECT_ONBOARDING: '项目接手',
    ENGINEERING_DECISION: '研发决策'
  }[type] || type || ''
}

function runStatusLabel(status) {
  return {
    CREATED: '排队中',
    CONTEXT_BUILDING: '构建上下文',
    ANALYZING: '分析中',
    VERIFYING: '复核中',
    PLANNING: '规划中',
    WAITING_APPROVAL: '待审批',
    COMPLETED: '已完成',
    FAILED: '失败'
  }[status] || status || '未知'
}

function relativeTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return String(value).replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.run-feed {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.run-feed.compact {
  max-height: 380px;
  overflow-y: auto;
}

.run-feed-empty {
  padding: 14px 0 4px;
  color: var(--atlas-muted);
  font-size: 12px;
  text-align: center;
}

.run-feed-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
  padding: 8px 0;
  border-bottom: 1px solid var(--atlas-border);
  cursor: pointer;
  transition: background 0.15s;
}

.run-feed-row:hover {
  background: var(--atlas-surface-soft);
  margin: 0 -8px;
  padding-left: 8px;
  padding-right: 8px;
  border-radius: 3px;
}

.run-feed-row.just-finished {
  animation: highlight-pulse 1s ease-out 2;
}

@keyframes highlight-pulse {
  0%, 100% { background: transparent; }
  50% { background: rgba(63, 127, 93, 0.08); }
}

.run-feed-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--atlas-subtle);
}

.run-feed-dot.ok { background: #3f7f5d; }
.run-feed-dot.error { background: #b35c56; }
.run-feed-dot.active { background: var(--atlas-warning); animation: dot-pulse 1.5s ease-in-out infinite; }
.run-feed-dot.waiting { background: var(--atlas-primary); }

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.run-feed-copy {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  gap: 3px;
}

.run-feed-headline {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.run-feed-headline strong {
  overflow: hidden;
  color: var(--atlas-text);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-feed-type {
  flex: 0 0 auto;
  padding: 1px 5px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 3px;
  font-size: 9px;
  font-weight: 800;
  white-space: nowrap;
}

.run-feed-step {
  overflow: hidden;
  color: var(--atlas-subtle);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-feed-progress {
  height: 3px;
  margin-top: 3px;
  background: var(--atlas-border);
  border-radius: 2px;
}

.run-feed-progress i {
  display: block;
  height: 100%;
  background: var(--atlas-warning);
  border-radius: 2px;
  transition: width 0.6s ease;
}

.run-feed-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex: 0 0 auto;
}

.run-feed-status {
  font-size: 10px;
  font-weight: 800;
  white-space: nowrap;
}

.run-feed-status.ok { color: #3f7f5d; }
.run-feed-status.error { color: #b35c56; }
.run-feed-status.active { color: var(--atlas-warning); }
.run-feed-status.waiting { color: var(--atlas-primary); }

.run-feed time {
  color: var(--atlas-subtle);
  font-size: 9px;
  white-space: nowrap;
}

.run-feed-footer {
  padding: 8px 0 2px;
  color: var(--atlas-subtle);
  font-size: 10px;
  text-align: center;
}
</style>
