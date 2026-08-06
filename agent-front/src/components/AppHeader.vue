<template>
  <header class="header" :class="{ scrolled }">
    <div class="header-inner">
      <router-link to="/" class="logo">
        <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true"><path d="M4 4h16v16H4z"/><path d="M8 8h16v16H8z"/></svg>
        <span class="logo-text">AtlasMind</span>
      </router-link>
      <nav class="nav">
        <router-link to="/" class="nav-link"><span class="nav-label">工作台</span></router-link>
        <router-link to="/knowledge" class="nav-link"><span class="nav-label">Agent 参考库</span></router-link>
      </nav>
      <div class="search-box" @submit.prevent="doSearch">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input v-model="keyword" type="text" class="search-input" placeholder="搜索项目或证据..." @keyup.enter="doSearch"/>
      </div>
      <div class="header-actions">
        <!-- 消息中心 -->
        <div class="notification-wrap" @click.stop>
          <button type="button" class="notification-button" title="消息中心" aria-label="消息中心" @click="toggleNotificationPanel">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            <span v-if="notificationBadgeCount > 0" class="notification-badge">{{ notificationBadgeCount > 99 ? '99+' : notificationBadgeCount }}</span>
          </button>
          <div v-if="notificationOpen" class="notification-panel" @click.stop @wheel.stop>
            <!-- 外部模型状态（最顶部） -->
            <div class="panel-section-heading">
              <strong>外部模型状态</strong>
              <button type="button" class="icon-refresh" title="重新检测" :disabled="aiStatusLoading" @click="refreshAiStatus">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8.1 8.1 0 0 0-14.8-4L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8.1 8.1 0 0 0 14.8 4L21 15"/><path d="M21 20v-5h-5"/></svg>
              </button>
            </div>
            <div class="model-status-list">
              <div v-for="item in modelStatusItems" :key="item.key" class="model-status-row">
                <span>{{ item.label }}</span>
                <strong :class="statusClass(item.status)">{{ statusLabel(item.status) }}</strong>
              </div>
            </div>
            <p v-if="aiStatusMessage" class="status-message">{{ aiStatusMessage }}</p>
            <time v-if="aiStatus?.checkedAt" class="checked-time">检测于 {{ formatTime(aiStatus.checkedAt) }}</time>

            <div class="panel-divider"></div>

            <div class="panel-section-heading">
              <strong>合同处理</strong>
              <span class="section-note">文件、Agent 与结果</span>
            </div>
            <div v-if="contractActivities.length" class="contract-activity-feed">
              <div
                v-for="activity in contractActivities"
                :key="activity.id"
                class="contract-activity-row"
                :class="activityStatusClass(activity)"
                role="button"
                tabindex="0"
                @click="openContractActivity(activity)"
                @keydown.enter="openContractActivity(activity)"
              >
                <span class="activity-dot" :class="activityStatusClass(activity)"></span>
                <div class="contract-activity-copy">
                  <div class="activity-headline">
                    <strong>{{ activity.caseTitle }}</strong>
                    <span class="activity-kind">{{ activity.kind === 'CONTRACT_WORKFLOW' ? '合同工作流' : 'Agent 任务' }}</span>
                  </div>
                  <span class="activity-main-label">{{ activityMainLabel(activity) }}</span>
                  <div class="activity-stage-list">
                    <div v-if="activity.pipeline" class="activity-stage">
                      <span>文件</span>
                      <strong>{{ pipelineActionLabel(activity.pipeline) }}</strong>
                      <b>{{ pipelineIsActive(activity.pipeline.status) ? `${activity.pipeline.progress || 0}%` : pipelineStatusLabel(activity.pipeline.status) }}</b>
                    </div>
                    <div v-if="activity.run" class="activity-stage">
                      <span>Agent</span>
                      <strong>{{ activity.run.currentStep || runTypeLabel(activity.run.runType) }}</strong>
                      <b>{{ runIsActive(activity.run.status) ? `${activity.run.progress || 0}%` : runStatusLabel(activity.run.status) }}</b>
                    </div>
                  </div>
                  <div v-if="activityIsActive(activity)" class="pipeline-progress">
                    <i :style="{ width: `${activityProgress(activity)}%` }"></i>
                  </div>
                  <p v-if="activity.status === 'FAILED'" class="activity-error-preview">
                    {{ activityFailureMessage(activity) }}
                  </p>
                </div>
                <div class="activity-meta">
                  <b>{{ activityStatusLabel(activity) }}</b>
                  <span v-if="activity.status === 'FAILED'" class="activity-error-link">查看原因</span>
                  <time>{{ relativeTime(activityUpdatedAt(activity)) }}</time>
                </div>
              </div>
            </div>
            <div v-else class="activity-empty">暂无合同处理记录</div>
          </div>
        </div>
        <a class="admin-link" :href="adminUrl" target="_blank" rel="noreferrer">管理端</a>
        <button type="button" class="logout-button" @click="logout">退出</button>
      </div>
    </div>
    <Teleport to="body">
      <div
        v-if="failureDialog"
        class="activity-error-overlay"
        role="presentation"
        @click.self="failureDialog = null"
      >
        <section
          class="activity-error-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-live="assertive"
          aria-labelledby="activity-error-title"
        >
          <div class="activity-error-dialog-head">
            <div>
              <span class="activity-error-kicker">合同处理失败</span>
              <h3 id="activity-error-title">查看失败原因</h3>
            </div>
            <button type="button" class="activity-error-close" aria-label="关闭" @click="failureDialog = null">×</button>
          </div>
          <dl class="activity-error-facts">
            <div>
              <dt>合同</dt>
              <dd>{{ failureDialog.caseTitle }}</dd>
            </div>
            <div v-if="failureDialog.run?.id">
              <dt>Agent Run</dt>
              <dd>#{{ failureDialog.run.id }}</dd>
            </div>
            <div v-if="failureDialog.run?.currentStep">
              <dt>失败阶段</dt>
              <dd>{{ failureDialog.run.currentStep }}</dd>
            </div>
          </dl>
          <div class="activity-error-message">
            <span>系统返回的失败原因</span>
            <p>{{ activityFailureMessage(failureDialog) }}</p>
          </div>
          <div class="activity-error-actions">
            <button type="button" class="quiet-button" @click="failureDialog = null">关闭</button>
            <button type="button" class="primary-button small" @click="openFailureCase">查看合同详情</button>
          </div>
        </section>
      </div>
    </Teleport>
  </header>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getRecentContractDocumentPipelines, getRecentWorkspaceRuns, getWorkspaceAiStatus, getWorkspaceUnreadCount } from '../api/index.js'
import { activityProgress as getActivityProgress, isActivityActive, mergeContractActivities } from '../utils/contractActivity.js'

const router = useRouter()
const message = useMessage()
const keyword = ref('')
const scrolled = ref(false)
const adminUrl = import.meta.env.VITE_ADMIN_URL || 'http://localhost:15173/'
const notificationOpen = ref(false)
const failureDialog = ref(null)
const unreadCount = ref(0)
const aiStatus = ref(null)
const aiStatusLoading = ref(false)
const recentRuns = ref([])
const documentPipelines = ref([])
let refreshTimer = null

const modelStatusItems = computed(() => {
  const components = aiStatus.value?.components || {}
  return [
    { key: 'llm', label: 'LLM / DeepSeek', status: components.llm?.status || 'unknown' },
    { key: 'embedding', label: 'Embedding', status: components.embedding?.status || 'unknown' },
    { key: 'elasticsearch', label: 'Elasticsearch', status: components.elasticsearch?.status || 'unknown' }
  ]
})
const aiStatusMessage = computed(() => {
  const components = aiStatus.value?.components || {}
  return Object.values(components).find(item => item?.message)?.message || ''
})
const contractActivities = computed(() => mergeContractActivities(documentPipelines.value, recentRuns.value, 8))
const activeContractActivityCount = computed(() => contractActivities.value.filter(activity => isActivityActive(activity)).length)
const notificationBadgeCount = computed(() => unreadCount.value + activeContractActivityCount.value)
const previousActivityStatuses = ref({})

watch(contractActivities, (activities) => {
  const previous = previousActivityStatuses.value
  for (const activity of activities) {
    const before = previous[activity.id]
    const after = String(activity.status || '').toUpperCase()
    if (!before || before === after || !['COMPLETED', 'FAILED'].includes(after)) continue
    if (!isActivityActive({ status: before })) continue
    const label = activity.run?.runType ? runTypeLabel(activity.run.runType) : '合同处理'
    if (after === 'COMPLETED') message.success(`${label}已完成 · ${activity.caseTitle}`)
    else message.error(`${label}失败 · ${activity.caseTitle}`)
  }
  previousActivityStatuses.value = Object.fromEntries(
    activities.map(activity => [activity.id, String(activity.status || '').toUpperCase()]),
  )
})

if (typeof window !== 'undefined') {
  window.addEventListener('scroll', () => { scrolled.value = window.scrollY > 10 })
}

onMounted(() => {
  refreshHeaderData(); refreshAiStatus()
  document.addEventListener('click', closeNotificationPanel)
  refreshTimer = window.setInterval(refreshAll, 8000)
})
onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  document.removeEventListener('click', closeNotificationPanel)
})

async function refreshAll() {
  try {
    const [countRes, runsRes, pipelinesRes] = await Promise.allSettled([
      getWorkspaceUnreadCount(),
      getRecentWorkspaceRuns(),
      getRecentContractDocumentPipelines(),
    ])
    if (countRes.status === 'fulfilled') unreadCount.value = Number(countRes.value.data.data?.count) || 0
    if (runsRes.status === 'fulfilled') recentRuns.value = runsRes.value.data.data || []
    if (pipelinesRes.status === 'fulfilled') documentPipelines.value = pipelinesRes.value.data.data || []
  } catch { /* silent */ }
}
async function refreshHeaderData() {
  try {
    const [countRes, runsRes, pipelinesRes] = await Promise.allSettled([
      getWorkspaceUnreadCount(),
      getRecentWorkspaceRuns(),
      getRecentContractDocumentPipelines(),
    ])
    if (countRes.status === 'fulfilled') unreadCount.value = Number(countRes.value.data.data?.count) || 0
    if (runsRes.status === 'fulfilled') recentRuns.value = runsRes.value.data.data || []
    if (pipelinesRes.status === 'fulfilled') documentPipelines.value = pipelinesRes.value.data.data || []
  } catch { /* silent */ }
}
async function refreshAiStatus() {
  aiStatusLoading.value = true
  try { const r = await getWorkspaceAiStatus(); aiStatus.value = r.data.data || null }
  catch { aiStatus.value = { status:'error', components:{ llm:{status:'error',message:'无法连接'} } } }
  finally { aiStatusLoading.value = false }
}

function doSearch() { router.push({ path:'/', query: keyword.value.trim() ? { keyword: keyword.value } : {} }) }
function logout() { localStorage.removeItem('atlasmind-token'); router.push('/login') }

async function toggleNotificationPanel() {
  notificationOpen.value = !notificationOpen.value
  if (notificationOpen.value) {
    await refreshHeaderData()
    await refreshAiStatus()
  }
}
function closeNotificationPanel() { notificationOpen.value = false }

function openContractActivity(activity) {
  if (activity?.status === 'FAILED') {
    failureDialog.value = activity
    return
  }
  if (activity?.caseId) {
    router.push({
      path: `/contracts/${activity.caseId}`,
      query: activity.run?.id ? { runId: String(activity.run.id) } : undefined,
    })
  }
}
function activityFailureMessage(activity) {
  return activity?.run?.errorMessage
    || activity?.pipeline?.errorMessage
    || activity?.pipeline?.pipelineError
    || '系统没有返回具体失败原因，请打开合同详情查看运行记录。'
}
function openFailureCase() {
  const activity = failureDialog.value
  failureDialog.value = null
  notificationOpen.value = false
  if (activity?.caseId) {
    router.push({
      path: `/contracts/${activity.caseId}`,
      query: activity.run?.id ? { runId: String(activity.run.id) } : undefined,
    })
  }
}
function pipelineIsActive(status) {
  return !['READY', 'COMPLETED', 'FAILED', 'CANCELLED'].includes(String(status || '').toUpperCase())
}
function pipelineStatusClass(status) {
  const normalized = String(status || '').toUpperCase()
  if (['READY', 'COMPLETED'].includes(normalized)) return 'done'
  if (['FAILED', 'CANCELLED'].includes(normalized)) return 'error'
  return 'active'
}
function pipelineStatusLabel(status) {
  return { UPLOADED: '已提交', PROCESSING: '处理中', READY: '已完成', FAILED: '失败', CANCELLED: '已取消' }[String(status || '').toUpperCase()] || '处理中'
}
function pipelineActionLabel(pipeline) {
  if (pipeline?.currentAction) return pipeline.currentAction
  const stage = String(pipeline?.stage || '').toUpperCase()
  const labels = {
    UPLOADED: '正在准备合同文件',
    DOCUMENT_START: '正在读取合同文件',
    TEXT_PARSING: '正在读取合同文字',
    PDF_PARSING: '正在读取合同文字',
    PDF_RECOGNITION_OPTIMIZATION: '正在优化文字识别',
    DOC_CONVERSION: '正在整理 Word 文档',
    DOCX_PARSING: '正在读取 Word 文档',
    CLAUSE_SPLITTING: '正在识别合同条款',
    CLAUSE_PERSISTING: '正在保存条款证据',
    TIMELINE_EXTRACTING: '正在提取合同时间节点',
    LIFECYCLE_EXTRACTING: '正在识别合同结束条件',
    EMBEDDING: '正在建立合同语义检索',
    INDEXING: '正在整理合同检索索引',
    READY: '合同解析已完成',
    FAILED: '合同解析失败',
  }
  return labels[stage] || pipelineStatusLabel(pipeline?.status)
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

function activityIsActive(activity) { return isActivityActive(activity) }
function activityStatusClass(activity) {
  const status = String(activity?.status || '').toUpperCase()
  if (status === 'COMPLETED') return 'done'
  if (status === 'FAILED') return 'error'
  if (activityIsActive(activity)) return 'active'
  return 'unknown'
}
function activityStatusLabel(activity) {
  const status = String(activity?.status || '').toUpperCase()
  if (status === 'COMPLETED') return '已完成'
  if (status === 'FAILED') return '失败'
  if (activityIsActive(activity)) return '处理中'
  return '待处理'
}
function activityMainLabel(activity) {
  if (activity?.pipeline && pipelineIsActive(activity.pipeline.status)) return pipelineActionLabel(activity.pipeline)
  if (activity?.run && runIsActive(activity.run.status)) {
    return activity.run.currentStep || `${runTypeLabel(activity.run.runType)}进行中`
  }
  if (activity?.pipeline?.status === 'FAILED' || activity?.run?.status === 'FAILED') return '合同处理失败，点击查看原因'
  if (activity?.run?.status === 'COMPLETED') return '审查结果已生成，点击查看合同详情'
  if (activity?.pipeline?.status === 'READY') return '合同文件处理完成，等待下一步'
  return '合同处理记录'
}
function activityProgress(activity) { return getActivityProgress(activity) }
function runIsActive(status) {
  return !['COMPLETED', 'FAILED', 'CANCELLED'].includes(String(status || '').toUpperCase())
}
function runTypeLabel(type) {
  return {
    CONTRACT_REVIEW: '合同审查',
    CONTRACT_INTAKE: '合同发起',
    APPROVAL_DECISION: '审批决策',
    VERSION_REVIEW: '版本复核',
    OBLIGATION_EXTRACTION: '义务提取',
    FULFILLMENT_CHECK: '履约核验',
    HEALTH_ANALYSIS: '健康分析',
    PROJECT_ONBOARDING: '项目接手',
    ENGINEERING_DECISION: '研发决策',
  }[type] || type || 'Agent 任务'
}
function runStatusLabel(status) {
  return {
    CREATED: '排队中',
    CONTEXT_BUILDING: '构建上下文',
    PLANNING: '规划中',
    ANALYZING: '分析中',
    VERIFYING: '复核中',
    WAITING_HUMAN: '等待人工确认',
    WAITING_APPROVAL: '等待审批',
    COMPLETED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
  }[status] || status || '未知'
}
function activityUpdatedAt(activity) {
  return activity?.pipeline?.updateTime || activity?.pipeline?.createTime
    || activity?.run?.updateTime || activity?.run?.createTime
}

function formatTime(v) { if (!v) return '刚刚'; const d = new Date(v); return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('zh-CN',{hour12:false}) }
function statusLabel(s) { return { ok:'可用', configured:'已配置', checking:'检测中', error:'不可用', degraded:'异常', info:'未配置', unknown:'未检测' }[String(s||'').toLowerCase()] || String(s||'未检测') }
function statusClass(s) { const n = String(s||'').toLowerCase(); if (['ok','completed','done'].includes(n)) return 'ok'; if (['error','failed'].includes(n)) return 'error'; if (['checking','created','context_building','analyzing','verifying','planning'].includes(n)) return 'checking'; return 'unknown' }
</script>

<style scoped>
.header{position:sticky;top:0;z-index:100;background:rgba(247,248,251,.88);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--atlas-border);transition:box-shadow .25s,background .25s}
.header.scrolled{background:rgba(255,255,255,.94);box-shadow:0 8px 24px rgba(15,23,42,.06)}
.header-inner{max-width:1120px;margin:0 auto;padding:0 24px;display:flex;justify-content:space-between;align-items:center;height:60px;gap:24px;box-sizing:border-box}
.logo{display:flex;align-items:center;gap:8px;text-decoration:none}
.logo-mark{width:30px;height:30px;flex:0 0 auto;fill:none;stroke:var(--atlas-primary);stroke-width:2;stroke-linejoin:round}
.logo-text{color:var(--atlas-text);font-family:Georgia,'Times New Roman',serif;font-size:19px;font-weight:700}
.nav{display:flex;gap:2px;flex:1;min-width:0;justify-content:center}
.nav-link{padding:7px 12px;border-radius:6px;text-decoration:none;font-size:14px;color:var(--atlas-muted);transition:all .15s}
.nav-link:hover{background:var(--atlas-surface-soft);color:var(--atlas-text)}
.nav-link.router-link-active{color:var(--atlas-primary);font-weight:700;box-shadow:inset 0 -2px 0 var(--atlas-primary)}
.search-box{display:flex;align-items:center;gap:6px;height:34px;padding:0 10px;border-radius:4px;background:var(--atlas-surface);border:1px solid var(--atlas-border);transition:border-color .2s,box-shadow .2s;min-width:0}
.search-box:focus-within{border-color:var(--atlas-primary);box-shadow:0 0 0 3px rgba(66,111,166,.12)}
.search-icon{color:#c0c4cc;flex-shrink:0;transition:color .2s}
.search-box:focus-within .search-icon{color:var(--atlas-primary)}
.search-input{border:none;outline:none;background:transparent;font-size:13px;color:var(--atlas-text);width:130px;font-family:inherit}
.search-input::placeholder{color:#c0c4cc}
.header-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto}

/* Notification */
.notification-wrap{position:relative}
.notification-button,.icon-refresh{display:inline-flex;align-items:center;justify-content:center;position:relative;border:1px solid var(--atlas-border);background:var(--atlas-surface);color:var(--atlas-muted);cursor:pointer}
.notification-button{width:34px;height:34px;border-radius:4px}
.notification-button:hover,.icon-refresh:hover:not(:disabled){color:var(--atlas-primary);border-color:var(--atlas-primary)}
.notification-badge{position:absolute;top:-6px;right:-6px;min-width:16px;height:16px;padding:0 4px;border-radius:8px;background:#b35c56;color:#fff;font-size:9px;font-weight:800;line-height:16px;text-align:center}
.notification-panel{position:absolute;top:calc(100% + 10px);right:0;z-index:110;width:390px;max-width:calc(100vw - 32px);max-height:min(580px, calc(100vh - 86px));overflow-y:auto;overflow-x:hidden;padding:14px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;box-shadow:0 14px 30px rgba(15,23,42,.14)}
.panel-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.panel-section-heading strong{color:var(--atlas-text);font-size:13px}
.section-note{color:var(--atlas-subtle);font-size:10px}
.panel-divider{height:1px;margin:14px 0;background:var(--atlas-border)}
.icon-refresh{width:26px;height:26px;border-radius:4px}
.icon-refresh:disabled{cursor:wait;opacity:.55}
.model-status-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px}
.model-status-row{min-width:0;padding:8px;border:1px solid var(--atlas-border);background:var(--atlas-bg)}
.model-status-row span{display:block;overflow:hidden;color:var(--atlas-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.model-status-row strong{display:block;margin-top:4px;font-size:11px}
.model-status-row strong.ok{color:#3f7f5d}.model-status-row strong.error{color:#b35c56}.model-status-row strong.checking{color:var(--atlas-warning)}.model-status-row strong.unknown{color:var(--atlas-subtle)}
.status-message{margin:8px 0 0;color:#b35c56;font-size:10px;line-height:1.5;overflow-wrap:anywhere}
.checked-time{display:block;margin-top:8px;color:var(--atlas-subtle);font-size:10px}
.contract-activity-feed{display:flex;flex-direction:column;margin-top:8px}
.contract-activity-row{display:flex;align-items:flex-start;gap:8px;min-width:0;padding:10px 0;border-bottom:1px solid var(--atlas-border);cursor:pointer;transition:background .15s}
.contract-activity-row:last-child{border-bottom:0}
.contract-activity-row:hover,.contract-activity-row:focus-visible{margin:0 -8px;padding-left:8px;padding-right:8px;background:var(--atlas-surface-soft);outline:0}
.activity-dot{width:7px;height:7px;flex:0 0 auto;margin-top:5px;border-radius:50%;background:var(--atlas-subtle)}
.activity-dot.active{background:var(--atlas-warning);animation:dot-pulse 1.5s ease-in-out infinite}
.activity-dot.done{background:#3f7f5d}.activity-dot.error{background:#b35c56}
.contract-activity-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:4px}
.activity-headline{display:flex;align-items:center;gap:6px;min-width:0}
.activity-headline strong{overflow:hidden;color:var(--atlas-text);font-size:11px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
.activity-kind{flex:0 0 auto;padding:1px 5px;color:var(--atlas-primary);background:var(--atlas-surface-soft);border:1px solid var(--atlas-border);border-radius:3px;font-size:9px;font-weight:800;white-space:nowrap}
.activity-main-label{overflow:hidden;color:var(--atlas-muted);font-size:10px;line-height:1.45;text-overflow:ellipsis;white-space:nowrap}
.activity-error-preview{margin:0;color:#8f4843;font-size:10px;line-height:1.5;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.activity-stage-list{display:grid;gap:3px}
.activity-stage{display:grid;grid-template-columns:30px minmax(0,1fr) auto;gap:5px;align-items:center;min-width:0;color:var(--atlas-subtle);font-size:9px}
.activity-stage>span{color:var(--atlas-primary);font-weight:900}
.activity-stage strong{overflow:hidden;font-size:9px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}
.activity-stage b{color:var(--atlas-muted);font-size:9px;font-weight:800;white-space:nowrap}
.activity-meta{display:flex;flex:0 0 auto;flex-direction:column;align-items:flex-end;gap:3px;color:var(--atlas-subtle);font-size:9px}
.activity-meta b{color:var(--atlas-primary);font-size:10px;white-space:nowrap}.contract-activity-row.error .activity-meta b{color:#b35c56}.contract-activity-row.done .activity-meta b{color:#3f7f5d}
.activity-error-link{color:#b35c56;font-size:9px;font-weight:800;white-space:nowrap}
.activity-empty{padding:16px 0 4px;color:var(--atlas-muted);font-size:12px;text-align:center}
.document-pipeline-feed{display:flex;flex-direction:column;margin-top:8px}
.document-pipeline-row{display:flex;align-items:flex-start;gap:8px;min-width:0;padding:9px 0;border-bottom:1px solid var(--atlas-border);cursor:pointer}
.document-pipeline-row:last-child{border-bottom:0}
.document-pipeline-row:hover{background:var(--atlas-surface-soft);margin:0 -8px;padding-left:8px;padding-right:8px}
.pipeline-dot{width:7px;height:7px;flex:0 0 auto;margin-top:5px;border-radius:50%;background:var(--atlas-warning)}
.pipeline-dot.active{animation:dot-pulse 1.5s ease-in-out infinite}
.pipeline-dot.done{background:#3f7f5d}.pipeline-dot.error{background:#b35c56}
.document-pipeline-copy{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px}
.document-pipeline-copy strong{overflow:hidden;color:var(--atlas-text);font-size:11px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
.document-pipeline-copy span{overflow:hidden;color:var(--atlas-muted);font-size:10px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}
.document-pipeline-meta{display:flex;flex:0 0 auto;flex-direction:column;align-items:flex-end;gap:3px;color:var(--atlas-subtle);font-size:10px}
.document-pipeline-meta b{color:var(--atlas-primary);font-size:10px;white-space:nowrap}.document-pipeline-row.error .document-pipeline-meta b{color:#b35c56}.document-pipeline-row.done .document-pipeline-meta b{color:#3f7f5d}
.pipeline-progress{height:3px;margin-top:2px;overflow:hidden;background:var(--atlas-border)}
.pipeline-progress i{display:block;height:100%;background:var(--atlas-primary);transition:width .35s ease}
.activity-error-overlay{position:fixed;inset:0;z-index:300;display:grid;place-items:center;padding:20px;background:rgba(22,35,48,.28)}
.activity-error-dialog{width:min(520px,100%);padding:20px;background:var(--atlas-surface);border:1px solid rgba(179,92,86,.35);border-left:4px solid #b35c56;border-radius:6px;box-shadow:0 18px 48px rgba(22,35,48,.18)}
.activity-error-dialog-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}
.activity-error-kicker{color:#b35c56;font-size:10px;font-weight:900;letter-spacing:.04em}
.activity-error-dialog h3{margin:4px 0 0;color:var(--atlas-text);font-size:18px}
.activity-error-close{width:28px;height:28px;border:1px solid var(--atlas-border);border-radius:4px;background:var(--atlas-surface);color:var(--atlas-muted);font-size:20px;line-height:1;cursor:pointer}
.activity-error-close:hover{color:#b35c56;border-color:#b35c56}
.activity-error-facts{display:grid;gap:9px;margin:18px 0 0}
.activity-error-facts div{display:grid;grid-template-columns:74px minmax(0,1fr);gap:10px;padding-bottom:8px;border-bottom:1px solid var(--atlas-border)}
.activity-error-facts dt{color:var(--atlas-subtle);font-size:10px;font-weight:900}
.activity-error-facts dd{margin:0;color:var(--atlas-text);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.activity-error-message{margin-top:16px;padding:12px;background:#fff6f5;border:1px solid #edcfcc;border-radius:4px}
.activity-error-message span{display:block;color:#9d4b45;font-size:10px;font-weight:900}
.activity-error-message p{margin:7px 0 0;color:#5f3532;font-size:12px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}
.activity-error-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}

.admin-link,.logout-button{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 10px;color:var(--atlas-muted);background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer;font-size:12px;font-weight:800;text-decoration:none;white-space:nowrap}
.admin-link:hover,.logout-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}

@media(max-width:860px){.header-inner{height:auto;min-height:60px;flex-wrap:wrap;gap:10px;padding:12px 16px}.nav{order:3;flex:0 0 100%;width:100%;min-width:0;overflow-x:auto;justify-content:flex-start;padding-bottom:2px}.nav-link{white-space:nowrap}.search-box{margin-left:auto;max-width:min(172px,calc(100vw - 190px))}.search-input{width:100%;min-width:0}}
@media(max-width:520px){.model-status-list{grid-template-columns:1fr}}
@media(max-width:520px){.activity-stage{grid-template-columns:30px minmax(0,1fr)}.activity-stage b{grid-column:2}.activity-meta{display:none}}
@media(max-width:420px){.header-inner{align-items:flex-start}.logo{min-height:34px}.search-box{order:2;flex:1 1 calc(100% - 96px);width:auto;max-width:none;margin-left:0}.header-actions{order:2;margin-left:auto}.notification-panel{position:fixed;top:70px;right:16px}.nav{order:3}}

[data-theme="dark"] .header{background:rgba(11,17,32,.88);border-bottom-color:var(--atlas-border)}
[data-theme="dark"] .header.scrolled{background:rgba(17,24,39,.94)}
[data-theme="dark"] .logo-mark{stroke:#8fb1d8}
[data-theme="dark"] .nav-link.router-link-active{color:#8fb1d8}
[data-theme="dark"] .search-box{background:var(--atlas-surface);border-color:var(--atlas-border)}
</style>
