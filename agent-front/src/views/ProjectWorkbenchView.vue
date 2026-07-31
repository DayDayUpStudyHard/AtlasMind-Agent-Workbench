<template>
  <div class="workbench-page">
    <div v-if="loading" class="loading-block">
      <span class="loader"></span>
      正在读取项目上下文
    </div>

    <template v-else-if="project">
      <header class="project-header">
        <div>
          <router-link to="/" class="back-link">返回项目总览</router-link>
          <div class="project-title-row">
            <span class="project-key">{{ project.projectKey }}</span>
            <span class="health-chip" :class="healthClass(project.healthStatus)">
              {{ healthLabel(project.healthStatus) }}
            </span>
          </div>
          <h1>{{ project.name }}</h1>
          <p>{{ project.description || '这个项目还没有补充说明。' }}</p>
        </div>
        <div class="project-header-actions">
          <a v-if="project.repositoryUrl" :href="project.repositoryUrl" target="_blank" rel="noreferrer" class="quiet-button">
            查看仓库
          </a>
          <button class="quiet-button" type="button" :disabled="syncing" @click="syncEvidence">
            {{ syncing ? '同步中' : '同步 GitHub 证据' }}
          </button>
          <button class="primary-button" type="button" :disabled="running" @click="runAnalysis">
            {{ running ? 'Agent 分析中' : '运行健康分析' }}
          </button>
        </div>
      </header>

      <section class="context-row">
        <div><span>当前里程碑</span><strong>{{ project.currentMilestone || '待设置' }}</strong></div>
        <div><span>目标版本</span><strong>{{ project.releaseTarget || '待设置' }}</strong></div>
        <div><span>团队规模</span><strong>{{ project.teamSize || '—' }} 人</strong></div>
        <div><span>技术栈</span><strong>{{ project.techStack || '待补充' }}</strong></div>
      </section>

      <section class="source-sync-panel">
        <div class="source-copy">
          <p class="section-kicker">证据来源</p>
          <h2>GitHub 只读证据同步</h2>
          <p>
            Agent Run 会优先读取这里沉淀的仓库、README、配置文件、Issue、PR 和 Commit 证据；
            没有证据时才回退到知识库检索和项目录入事实。
          </p>
        </div>
        <div class="source-status-grid">
          <div><span>同步状态</span><strong :class="sourceStatusClass(sourceStatus)">{{ sourceStatusLabel(sourceStatus) }}</strong></div>
          <div><span>证据条目</span><strong>{{ evidence.length }}</strong></div>
          <div><span>最近同步</span><strong>{{ latestSyncJob ? formatDate(latestSyncJob.finishedAt || latestSyncJob.createTime) : '尚未同步' }}</strong></div>
          <div><span>默认分支</span><strong>{{ project.defaultBranch || 'main' }}</strong></div>
        </div>
        <div v-if="latestSyncJob?.errorMessage" class="sync-error">{{ latestSyncJob.errorMessage }}</div>
      </section>

      <section class="health-layout">
        <div class="health-summary">
          <div class="summary-label">最新健康信号</div>
          <div class="summary-score">{{ project.healthScore || '—' }}<small>/100</small></div>
          <strong>{{ healthLabel(project.healthStatus) }}</strong>
          <p>{{ latestReport?.summary || '尚未运行分析。先同步证据，再启动一次 Agent Run，生成带引用的项目健康报告。' }}</p>
          <div class="summary-foot">
            <span>{{ latestReport ? formatDate(latestReport.createTime) : '等待首次运行' }}</span>
            <span v-if="latestReport">报告 #{{ latestReport.id }}</span>
          </div>
        </div>
        <div class="dimensions-panel">
          <div class="panel-heading">
            <div><p class="section-kicker">五维分析</p><h2>项目健康</h2></div>
            <span class="evidence-note">证据复核 Agent 核验后更新</span>
          </div>
          <div class="dimension-grid">
            <div v-for="item in dimensions" :key="item.name" class="dimension">
              <div class="dimension-top"><span>{{ item.name }}</span><strong>{{ item.score }}</strong></div>
              <div class="dimension-bar"><i :style="{ width: `${item.score}%` }"></i></div>
              <p>{{ item.note }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="content-grid">
        <div class="main-column">
          <section class="panel-section">
            <div class="panel-heading">
              <div><p class="section-kicker">证据报告</p><h2>关键风险</h2></div>
              <span v-if="latestReport" class="report-status">{{ reportStatusLabel(latestReport.status) }}</span>
            </div>
            <div v-if="risks.length" class="risk-list">
              <article v-for="risk in risks" :key="risk.id" class="risk-row">
                <div class="risk-marker" :class="severityClass(risk.severity)"></div>
                <div class="risk-body">
                  <div class="risk-top"><strong>{{ risk.title }}</strong><span>{{ severityLabel(risk.severity) }}</span></div>
                  <p>{{ risk.description }}</p>
                  <small v-if="risk.citation">证据：{{ risk.citation.title }} · {{ risk.citation.snippet }}</small>
                </div>
              </article>
            </div>
            <div v-else class="blank-state">运行一次分析后，这里会显示带引用的风险清单。</div>
          </section>

          <section class="panel-section">
            <div class="panel-heading">
              <div><p class="section-kicker">交付计划</p><h2>下一阶段交付计划</h2></div>
              <span class="evidence-note">人工确认后执行</span>
            </div>
            <div v-if="plan.length" class="plan-list">
              <div v-for="task in plan" :key="task.id" class="plan-row">
                <span class="plan-id">{{ task.id }}</span>
                <div><strong>{{ task.title }}</strong><p>{{ task.acceptance }}</p></div>
                <span class="plan-owner">{{ task.ownerRole }}</span>
              </div>
            </div>
            <div v-else class="blank-state">交付规划会在健康分析完成后生成。</div>
          </section>

          <section class="panel-section">
            <div class="panel-heading">
              <div><p class="section-kicker">引用来源</p><h2>报告引用来源</h2></div>
              <span class="evidence-note">{{ citations.length }} 条</span>
            </div>
            <div v-if="citations.length" class="citation-list">
              <a v-for="citation in citations" :key="`${citation.sourceType}-${citation.sourceId}-${citation.rank}`" class="citation-row" :href="citation.sourceUrl || undefined" target="_blank" rel="noreferrer">
                <span class="citation-type">{{ objectLabel(citation.objectType || citation.sourceType) }}</span>
                <div>
                  <strong>{{ citation.title }}</strong>
                  <p>{{ citation.snippet }}</p>
                  <small>{{ citation.sourceRef || citation.sourceId }} · 置信分 {{ scoreText(citation.score) }}</small>
                </div>
              </a>
            </div>
            <div v-else class="blank-state">报告生成后会列出实际引用的证据来源。</div>
          </section>

          <section v-if="latestReport?.reportMarkdown" class="panel-section report-section">
            <div class="panel-heading">
              <div><p class="section-kicker">报告产物</p><h2>完整报告</h2></div>
              <button class="quiet-button" type="button" @click="downloadMarkdown">导出 Markdown</button>
            </div>
            <div class="markdown-body" v-html="renderMarkdown(latestReport.reportMarkdown)"></div>
          </section>
        </div>

        <aside class="side-column">
          <section class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">Agent 运行</p><h2>运行记录</h2></div></div>
            <div v-if="runs.length" class="run-list">
              <button v-for="run in runs" :key="run.id" type="button" class="run-row" :class="{ active: selectedRun?.id === run.id }" @click="selectRun(run.id)">
                <span class="run-status" :class="String(run.status).toLowerCase()"></span>
                <span class="run-copy"><strong>运行 #{{ run.id }}</strong><small>{{ run.currentStep || runStatusLabel(run.status) }}</small></span>
                <span class="run-progress">{{ run.progress || 0 }}%</span>
              </button>
            </div>
            <div v-else class="blank-state">还没有运行记录。</div>
          </section>

          <section class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">审批闸门</p><h2>待审批动作</h2></div></div>
            <div v-if="pendingActions.length" class="action-list">
              <div v-for="action in pendingActions" :key="action.id" class="action-card">
                <span class="action-label">{{ actionTypeLabel(action.actionType) }}</span>
                <strong>{{ action.title }}</strong>
                <p>Agent 已生成草稿，确认后才会调用 GitHub 写接口。</p>
                <div class="action-buttons">
                  <button v-if="action.status === 'PENDING_APPROVAL'" type="button" class="primary-button small" @click="approveAction(action)">批准</button>
                  <button v-if="action.status === 'PENDING_APPROVAL'" type="button" class="quiet-button small" @click="rejectAction(action)">驳回</button>
                </div>
                <small v-if="action.errorMessage" class="action-error">{{ action.errorMessage }}</small>
              </div>
            </div>
            <div v-else class="blank-state">当前没有待审批外部动作。</div>
          </section>

          <section class="side-panel">
            <div class="panel-heading"><div><p class="section-kicker">证据库存</p><h2>证据库存</h2></div></div>
            <div v-if="evidenceSummary.length" class="inventory-list">
              <div v-for="item in evidenceSummary" :key="item.objectType" class="inventory-row">
                <span>{{ objectLabel(item.objectType) }}</span><strong>{{ item.count }}</strong>
              </div>
            </div>
            <div v-if="evidence.length" class="evidence-list">
              <a v-for="item in evidence.slice(0, 8)" :key="item.id" :href="item.sourceUrl || undefined" target="_blank" rel="noreferrer" class="evidence-row">
                <span>{{ objectLabel(item.objectType) }}</span>
                <strong>{{ item.title }}</strong>
                <small>{{ item.sourceRef || item.sourceUrl }}</small>
              </a>
            </div>
            <div v-else class="blank-state">同步 GitHub 后会展示可引用证据。</div>
          </section>

          <section class="side-panel source-panel">
            <div class="panel-heading"><div><p class="section-kicker">项目上下文</p><h2>长期记忆</h2></div></div>
            <div v-if="project.memories?.length" class="memory-list">
              <div v-for="memory in project.memories" :key="memory.id" class="memory-row">
                <span>{{ memoryTypeLabel(memory.memoryType) }}</span><strong>{{ memory.title }}</strong><p>{{ memory.content }}</p>
              </div>
            </div>
            <div v-else class="blank-state">项目事实和决策确认后会沉淀在这里。</div>
          </section>
        </aside>
      </section>
    </template>

    <div v-else class="blank-state page-blank">没有找到这个项目。</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { useMessage } from 'naive-ui'
import { useRoute } from 'vue-router'
import {
  approveProjectAction,
  getProject,
  getProjectEvidence,
  getProjectRun,
  startProjectRun,
  syncProjectEvidence
} from '../api/index.js'

const route = useRoute()
const message = useMessage()
const loading = ref(true)
const running = ref(false)
const syncing = ref(false)
const project = ref(null)
const evidence = ref([])
const selectedRun = ref(null)

const latestReport = computed(() => project.value?.reports?.[0] || null)
const latestSyncJob = computed(() => project.value?.syncJobs?.[0] || null)
const evidenceSummary = computed(() => project.value?.evidenceSummary || [])
const dimensions = computed(() => parseJson(latestReport.value?.dimensionsJson))
const risks = computed(() => parseJson(latestReport.value?.risksJson))
const plan = computed(() => parseJson(latestReport.value?.planJson))
const citations = computed(() => parseJson(latestReport.value?.citationsJson))
const runs = computed(() => project.value?.runs || [])
const sourceStatus = computed(() => project.value?.sources?.[0]?.status || 'PENDING')
const pendingActions = computed(() => selectedRun.value?.actions?.filter(action => ['PENDING_APPROVAL', 'APPROVED', 'BLOCKED'].includes(action.status)) || [])

onMounted(loadProject)

async function loadProject() {
  loading.value = true
  try {
    const response = await getProject(route.params.id)
    project.value = response.data.data
    await loadEvidence()
    if (project.value?.runs?.[0]) await selectRun(project.value.runs[0].id)
  } catch (error) {
    message.error(error.response?.data?.message || '项目加载失败')
  } finally {
    loading.value = false
  }
}

async function loadEvidence() {
  const response = await getProjectEvidence(route.params.id, { limit: 50 })
  evidence.value = response.data.data || []
}

async function syncEvidence() {
  syncing.value = true
  try {
    const response = await syncProjectEvidence(route.params.id)
    const job = response.data.data
    if (job?.status === 'FAILED') {
      message.error(job.errorMessage || 'GitHub 证据同步失败')
    } else {
      message.success('GitHub 证据已同步')
    }
    await loadProject()
  } catch (error) {
    message.error(error.response?.data?.message || 'GitHub 证据同步失败')
  } finally {
    syncing.value = false
  }
}

async function runAnalysis() {
  running.value = true
  try {
    const response = await startProjectRun(route.params.id, { triggerType: 'MANUAL' })
    selectedRun.value = response.data.data
    message.success('Agent Run 已创建，正在后台分析')
    await pollRun(selectedRun.value.id)
  } catch (error) {
    message.error(error.response?.data?.message || '无法启动 Agent Run')
  } finally {
    running.value = false
  }
}

async function pollRun(runId) {
  for (let i = 0; i < 20; i += 1) {
    await new Promise(resolve => setTimeout(resolve, 700))
    const response = await getProjectRun(runId)
    selectedRun.value = response.data.data
    if (['WAITING_APPROVAL', 'COMPLETED', 'FAILED'].includes(selectedRun.value.status)) break
  }
  await loadProject()
}

async function selectRun(id) {
  const response = await getProjectRun(id)
  selectedRun.value = response.data.data
}

async function approveAction(action) {
  try {
    const response = await approveProjectAction(selectedRun.value.id, action.id, { approved: true })
    selectedRun.value = response.data.data
    message.success('动作已批准，系统将异步执行外部连接器')
  } catch (error) {
    message.error(error.response?.data?.message || '审批失败')
  }
}

async function rejectAction(action) {
  try {
    const response = await approveProjectAction(selectedRun.value.id, action.id, { approved: false })
    selectedRun.value = response.data.data
    message.info('动作已驳回')
  } catch (error) {
    message.error(error.response?.data?.message || '审批失败')
  }
}

function parseJson(value) {
  if (!value) return []
  try { return JSON.parse(value) } catch { return [] }
}
function renderMarkdown(value) { return marked.parse(value || '', { breaks: true }) }
function downloadMarkdown() {
  const blob = new Blob([latestReport.value?.reportMarkdown || ''], { type: 'text/markdown;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${project.value.projectKey}-健康分析报告.md`
  link.click()
  URL.revokeObjectURL(link.href)
}
function formatDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
function scoreText(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(2) : '—'
}
function healthClass(status) { return String(status || 'UNKNOWN').toLowerCase() }
function healthLabel(status) { return { HEALTHY: '稳定', WATCH: '关注', AT_RISK: '有风险', UNKNOWN: '未分析' }[status] || '未分析' }
function sourceStatusClass(status) { return String(status || 'PENDING').toLowerCase() }
function sourceStatusLabel(status) { return { READY: '已就绪', SYNCING: '同步中', FAILED: '失败', PENDING: '待同步' }[status] || '待同步' }
function reportStatusLabel(status) { return { DRAFT: '草稿', PUBLISHED: '已发布', ARCHIVED: '已归档' }[status] || status || '未知' }
function runStatusLabel(status) {
  return {
    CREATED: '已创建',
    CONTEXT_BUILDING: '构建上下文',
    ANALYZING: '分析中',
    VERIFYING: '复核中',
    PLANNING: '规划中',
    WAITING_APPROVAL: '等待审批',
    COMPLETED: '已完成',
    FAILED: '失败'
  }[status] || status || '未知'
}
function severityClass(severity) {
  return { 高: 'high', 中: 'medium', 低: 'low', HIGH: 'high', MEDIUM: 'medium', LOW: 'low' }[severity] || 'medium'
}
function severityLabel(severity) {
  return { HIGH: '高', MEDIUM: '中', LOW: '低' }[severity] || severity || '待确认'
}
function actionTypeLabel(type) {
  return { CREATE_GITHUB_ISSUE: '创建 GitHub Issue' }[type] || type || '外部动作'
}
function memoryTypeLabel(type) {
  return { FACT: '事实', DECISION: '决策', RISK: '风险', PREFERENCE: '偏好', PROJECT_CONTEXT: '项目上下文' }[type] || type || '记忆'
}
function objectLabel(type) {
  return { GITHUB: 'GitHub', REPO: '仓库', README: 'README', FILE_TREE: '目录', FILE: '文件', ISSUE: 'Issue', PR: 'PR', COMMIT: 'Commit', PROJECT_CONTEXT: '项目事实' }[type] || type
}
</script>

<style scoped>
/* Hallmark | macrostructure: Project Workbench | tone: evidence-led operations | anchor hue: ink blue */
.workbench-page{display:flex;flex-direction:column;gap:26px;min-width:0;overflow-x:clip}.project-header{display:flex;justify-content:space-between;align-items:end;gap:30px;padding:10px 0 4px}.back-link{color:var(--atlas-primary);font-size:12px;font-weight:800;text-decoration:none}.project-title-row{display:flex;align-items:center;gap:10px;margin-top:24px}.project-key{color:var(--atlas-primary);font-size:12px;font-weight:800;letter-spacing:.06em}.health-chip{padding:4px 7px;border:1px solid currentColor;border-radius:3px;font-size:11px;font-weight:800}.health-chip.healthy{color:#3f7f5d;background:rgba(63,127,93,.06)}.health-chip.watch{color:var(--atlas-warning);background:rgba(167,121,61,.06)}.health-chip.at_risk{color:#b35c56;background:rgba(179,92,86,.06)}.health-chip.unknown{color:var(--atlas-subtle);background:var(--atlas-bg)}.project-header h1{margin:10px 0 7px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:clamp(36px,5vw,52px);line-height:1.06;overflow-wrap:anywhere}.project-header p{max-width:640px;margin:0;color:var(--atlas-muted);line-height:1.7}.project-header-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px}.quiet-button,.primary-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:0 14px;border-radius:4px;border:1px solid var(--atlas-border);font-size:13px;font-weight:800;cursor:pointer;text-decoration:none;white-space:nowrap}.quiet-button{color:var(--atlas-muted);background:var(--atlas-surface)}.quiet-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}.primary-button{color:#fff;background:var(--atlas-primary);border-color:var(--atlas-primary)}.primary-button:hover:not(:disabled){background:var(--atlas-primary-dark)}.primary-button.small,.quiet-button.small{min-height:34px;padding:0 10px;font-size:12px}button:disabled{cursor:not-allowed;opacity:.55}.context-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--atlas-border);border-bottom:1px solid var(--atlas-border)}.context-row div{display:flex;flex-direction:column;gap:5px;min-width:0;padding:15px 17px 14px 0;border-right:1px solid var(--atlas-border)}.context-row div:not(:first-child){padding-left:17px}.context-row div:last-child{border-right:0}.context-row span,.source-status-grid span{color:var(--atlas-subtle);font-size:11px;font-weight:800;text-transform:uppercase}.context-row strong,.source-status-grid strong{overflow-wrap:anywhere;color:var(--atlas-text);font-size:13px;line-height:1.4}.source-sync-panel{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.55fr);gap:20px;min-width:0;padding:19px 0;border-top:2px solid var(--atlas-primary);border-bottom:1px solid var(--atlas-border)}.source-copy{min-width:0}.section-kicker{margin:0;color:var(--atlas-primary);font-size:11px;font-weight:800;letter-spacing:.04em;text-transform:uppercase}.source-copy h2{margin:6px 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:28px;overflow-wrap:anywhere}.source-copy p:not(.section-kicker){max-width:720px;margin:0;color:var(--atlas-muted);font-size:13px;line-height:1.7}.source-status-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.source-status-grid div{min-width:0;padding:10px 12px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}.source-status-grid strong.ready{color:#3f7f5d}.source-status-grid strong.failed{color:#b35c56}.source-status-grid strong.syncing{color:var(--atlas-warning)}.sync-error{grid-column:1 / -1;padding:10px 12px;color:#8f3f3b;background:rgba(179,92,86,.08);border:1px solid rgba(179,92,86,.18);font-size:12px;line-height:1.5;overflow-wrap:anywhere}.health-layout{display:grid;grid-template-columns:minmax(210px,.32fr) minmax(0,.68fr);gap:14px}.health-summary,.dimensions-panel,.panel-section,.side-panel{min-width:0;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px}.health-summary{display:flex;flex-direction:column;padding:20px;border-top:2px solid var(--atlas-primary)}.summary-label{color:var(--atlas-subtle);font-size:11px;font-weight:800;text-transform:uppercase}.summary-score{margin-top:15px;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:55px;line-height:1}.summary-score small{margin-left:4px;color:var(--atlas-subtle);font-family:var(--atlas-font-body);font-size:13px}.health-summary>strong{margin-top:10px;color:var(--atlas-primary)}.health-summary>p{margin:13px 0 0;color:var(--atlas-muted);font-size:13px;line-height:1.7}.summary-foot{display:flex;justify-content:space-between;gap:8px;margin-top:auto;padding-top:20px;color:var(--atlas-subtle);font-size:11px}.dimensions-panel,.panel-section,.side-panel{padding:18px}.panel-heading{display:flex;align-items:end;justify-content:space-between;gap:14px}.panel-heading h2{margin:6px 0 0;color:var(--atlas-text);font-family:var(--atlas-font-display);font-size:23px;line-height:1.2}.evidence-note,.report-status{color:var(--atlas-subtle);font-size:11px}.dimension-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:19px 24px;margin-top:24px}.dimension{min-width:0}.dimension-top{display:flex;justify-content:space-between;gap:10px;color:var(--atlas-text);font-size:13px;font-weight:800}.dimension-top strong{color:var(--atlas-primary);font-family:var(--atlas-font-display);font-size:20px}.dimension-bar{height:5px;margin-top:8px;background:var(--atlas-surface-soft)}.dimension-bar i{display:block;height:100%;background:var(--atlas-primary)}.dimension p{margin:8px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.55}.content-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(270px,.36fr);gap:14px;align-items:start}.main-column,.side-column{display:flex;flex-direction:column;gap:14px;min-width:0}.panel-section{padding:20px}.risk-list,.plan-list,.run-list,.action-list,.memory-list,.citation-list,.evidence-list,.inventory-list{display:flex;flex-direction:column;gap:10px;margin-top:20px;min-width:0}.risk-row{display:grid;grid-template-columns:5px minmax(0,1fr);gap:13px;padding:11px 0;border-top:1px solid var(--atlas-border)}.risk-marker{width:5px;min-height:54px;background:var(--atlas-primary)}.risk-marker.high{background:#b35c56}.risk-marker.medium{background:var(--atlas-warning)}.risk-marker.low{background:#7d9a87}.risk-body{min-width:0}.risk-top{display:flex;justify-content:space-between;gap:12px}.risk-top strong{color:var(--atlas-text);font-size:14px;overflow-wrap:anywhere}.risk-top span{color:var(--atlas-warning);font-size:11px;font-weight:800}.risk-body p{margin:6px 0;color:var(--atlas-muted);font-size:13px;line-height:1.6}.risk-body small{display:-webkit-box;overflow:hidden;color:var(--atlas-subtle);font-size:11px;line-height:1.5;overflow-wrap:anywhere;-webkit-line-clamp:2;-webkit-box-orient:vertical}.plan-row{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:12px;align-items:start;padding:13px 0;border-top:1px solid var(--atlas-border)}.plan-id{color:var(--atlas-primary);font-family:var(--atlas-font-display);font-size:20px}.plan-row strong{color:var(--atlas-text);font-size:13px;overflow-wrap:anywhere}.plan-row p{margin:5px 0 0;color:var(--atlas-muted);font-size:12px;line-height:1.5}.plan-owner,.citation-type{padding:4px 6px;color:var(--atlas-primary);background:var(--atlas-surface-soft);font-size:10px;font-weight:800}.citation-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:12px;min-width:0;padding:12px 0;color:inherit;text-decoration:none;border-top:1px solid var(--atlas-border)}.citation-row>div{min-width:0}.citation-row:hover strong{color:var(--atlas-primary)}.citation-row strong{display:block;color:var(--atlas-text);font-size:13px;line-height:1.35;overflow-wrap:anywhere}.citation-row p{display:-webkit-box;margin:6px 0;overflow:hidden;color:var(--atlas-muted);font-size:12px;line-height:1.55;overflow-wrap:anywhere;-webkit-line-clamp:2;-webkit-box-orient:vertical}.citation-row small{color:var(--atlas-subtle);font-size:11px;overflow-wrap:anywhere}.run-row{display:flex;align-items:center;gap:9px;width:100%;padding:9px 0;color:inherit;background:transparent;border:0;border-bottom:1px solid var(--atlas-border);text-align:left;cursor:pointer}.run-row:hover .run-copy strong,.run-row.active .run-copy strong{color:var(--atlas-primary)}.run-status{width:8px;height:8px;flex:0 0 auto;background:var(--atlas-border-strong);border-radius:50%}.run-status.waiting_approval{background:var(--atlas-warning)}.run-status.completed{background:#3f7f5d}.run-status.failed{background:#b35c56}.run-copy{display:flex;flex-direction:column;min-width:0;flex:1;gap:3px}.run-copy strong{color:var(--atlas-text);font-size:12px}.run-copy small{overflow:hidden;color:var(--atlas-subtle);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.run-progress{color:var(--atlas-primary);font-size:10px;font-weight:800}.action-card{padding:12px;border:1px solid var(--atlas-border);border-left:3px solid var(--atlas-warning);background:var(--atlas-bg)}.action-label{color:var(--atlas-warning);font-size:10px;font-weight:800}.action-card strong{display:block;margin-top:7px;color:var(--atlas-text);font-size:13px;line-height:1.4;overflow-wrap:anywhere}.action-card p{margin:8px 0;color:var(--atlas-muted);font-size:11px;line-height:1.5}.action-buttons{display:flex;flex-wrap:wrap;gap:7px}.action-error{display:block;margin-top:8px;color:#8f3f3b;font-size:11px;line-height:1.4;overflow-wrap:anywhere}.inventory-row{display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--atlas-border)}.inventory-row span{color:var(--atlas-muted);font-size:12px}.inventory-row strong{color:var(--atlas-primary);font-family:var(--atlas-font-display)}.evidence-row,.memory-row{display:block;min-width:0;padding:9px 0;color:inherit;text-decoration:none;border-bottom:1px solid var(--atlas-border)}.evidence-row span,.memory-row span{color:var(--atlas-primary);font-size:10px;font-weight:800}.evidence-row strong,.memory-row strong{display:block;margin-top:5px;overflow:hidden;color:var(--atlas-text);font-size:12px;line-height:1.4;text-overflow:ellipsis;white-space:nowrap}.evidence-row small{display:block;margin-top:4px;overflow:hidden;color:var(--atlas-subtle);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.memory-row p{margin:4px 0 0;color:var(--atlas-muted);font-size:11px;line-height:1.5}.blank-state{padding:22px 0 5px;color:var(--atlas-muted);font-size:12px;line-height:1.6}.loading-block{display:flex;align-items:center;justify-content:center;gap:9px;min-height:50vh;color:var(--atlas-muted)}.loader{width:20px;height:20px;border:3px solid var(--atlas-border);border-top-color:var(--atlas-primary);border-radius:50%;animation:spin .8s linear infinite}.page-blank{padding:80px 0;text-align:center}.markdown-body{margin-top:20px;min-width:0;color:var(--atlas-muted);font-size:14px;line-height:1.8;overflow-wrap:anywhere}.markdown-body :deep(*){max-width:100%;overflow-wrap:anywhere}.markdown-body :deep(h1),.markdown-body :deep(h2),.markdown-body :deep(h3){color:var(--atlas-text);font-family:var(--atlas-font-display)}.markdown-body :deep(h1){font-size:28px}.markdown-body :deep(h2){margin-top:24px;padding-bottom:7px;border-bottom:1px solid var(--atlas-border);font-size:21px}.markdown-body :deep(p){margin:8px 0}.markdown-body :deep(blockquote){margin:12px 0;padding:9px 13px;border-left:3px solid var(--atlas-primary);background:var(--atlas-bg)}.markdown-body :deep(li){margin:5px 0}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:900px){.source-sync-panel,.health-layout,.content-grid{grid-template-columns:1fr}.side-column{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.source-panel{grid-column:1 / -1}}@media(max-width:650px){.project-header{align-items:flex-start;flex-direction:column}.project-header-actions{justify-content:stretch;width:100%}.project-header-actions .quiet-button,.project-header-actions .primary-button{flex:1 1 150px}.context-row,.source-status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.context-row div:nth-child(2){border-right:0}.context-row div:nth-child(3),.context-row div:nth-child(4){border-top:1px solid var(--atlas-border)}.context-row div:nth-child(3){padding-left:0}.side-column,.dimension-grid{grid-template-columns:1fr}.source-panel{grid-column:auto}}@media(max-width:420px){.project-header h1{font-size:36px}.panel-section,.side-panel,.dimensions-panel,.health-summary{padding:15px}.source-sync-panel{gap:14px}.source-status-grid{grid-template-columns:1fr}.plan-row{grid-template-columns:28px minmax(0,1fr)}.plan-owner{grid-column:2;justify-self:start}.citation-row{grid-template-columns:1fr}.citation-type{justify-self:start}}
</style>
