<template>
  <div class="dashboard">
    <section class="page-hero">
      <div>
        <span class="eyebrow">Agent Operations</span>
        <h2>研发项目 Agent 控制台</h2>
        <p>集中查看项目、证据、Agent Run、同步任务和审批状态，让后台从内容管理变成可追踪的企业 Agent 运维面板。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="$router.push('/projects')">项目管理</el-button>
        <el-button type="primary" @click="$router.push('/agent-runs')">查看 Run</el-button>
      </div>
    </section>

    <el-row :gutter="16" class="stat-row">
      <el-col :xs="24" :sm="12" :lg="6" v-for="item in statItems" :key="item.label">
        <div class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <span class="stat-hint">{{ item.hint }}</span>
        </div>
      </el-col>
    </el-row>

    <div class="dashboard-grid">
      <section class="panel work-panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Workflow</span>
            <h3>今日关注</h3>
          </div>
        </div>
        <div class="todo-list">
          <router-link to="/reports" class="todo-item">
            <span class="todo-dot warning"></span>
            <div>
              <strong>{{ stats.pendingApprovals }}</strong>
              <p>个 Agent 动作等待审批，避免自动化越过人工确认边界。</p>
            </div>
          </router-link>
          <router-link to="/evidence-sync" class="todo-item">
            <span class="todo-dot danger"></span>
            <div>
              <strong>{{ totalFailedJobs }}</strong>
              <p>个导入或同步任务失败，需要补证据来源或重试。</p>
            </div>
          </router-link>
          <router-link to="/agent-runs" class="todo-item">
            <span class="todo-dot primary"></span>
            <div>
              <strong>{{ stats.activeRuns }}</strong>
              <p>个 Agent Run 正在构建上下文、检索证据或生成计划。</p>
            </div>
          </router-link>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Run Trace</span>
            <h3>最近 Agent Run</h3>
          </div>
          <router-link to="/agent-runs">全部</router-link>
        </div>
        <div class="record-list" v-loading="loading">
          <router-link
            v-for="run in recentRuns"
            :key="run.id"
            to="/agent-runs"
            class="record-row"
          >
            <div>
              <strong>{{ run.projectName || `Project #${run.projectId}` }}</strong>
              <span>{{ run.currentStep || run.question || 'Agent Run' }}</span>
            </div>
            <em>{{ run.status }}</em>
          </router-link>
          <el-empty v-if="!loading && recentRuns.length === 0" description="暂无 Agent Run" :image-size="72" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="eyebrow">Evidence</span>
            <h3>最近同步任务</h3>
          </div>
          <router-link to="/evidence-sync">处理</router-link>
        </div>
        <div class="record-list" v-loading="loading">
          <div v-for="job in recentSyncJobs" :key="job.id" class="record-row">
            <div>
              <strong>{{ job.projectName || `Project #${job.projectId}` }}</strong>
              <span>{{ job.message || job.errorMessage || 'Evidence sync job' }}</span>
            </div>
            <em>{{ job.status }}</em>
          </div>
          <el-empty v-if="!loading && recentSyncJobs.length === 0" description="暂无同步任务" :image-size="72" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDashboardOverview } from '../api/index.js'

const loading = ref(false)
const stats = ref({
  projectCount: 0,
  knowledgeDocumentCount: 0,
  evidenceCount: 0,
  activeRuns: 0,
  pendingApprovals: 0,
  failedIngestJobCount: 0,
  failedSyncJobCount: 0
})
const recentRuns = ref([])
const recentSyncJobs = ref([])

const totalFailedJobs = computed(() => stats.value.failedIngestJobCount + stats.value.failedSyncJobCount)
const statItems = computed(() => [
  { label: '项目', value: stats.value.projectCount, hint: '纳入 Agent 管理的研发项目' },
  { label: '知识文档', value: stats.value.knowledgeDocumentCount, hint: '可被 RAG 检索的企业资料' },
  { label: '证据', value: stats.value.evidenceCount, hint: '来自仓库、文档和连接器的事实' },
  { label: '运行中 Run', value: stats.value.activeRuns, hint: '正在执行的 Agent 分析流程' },
  { label: '待审批', value: stats.value.pendingApprovals, hint: '需要人工确认的自动化动作' },
  { label: '失败任务', value: totalFailedJobs.value, hint: '导入或同步失败待处理' }
])

onMounted(fetchDashboard)

async function fetchDashboard() {
  loading.value = true
  try {
    const response = await getDashboardOverview()
    const data = response.data.data || {}
    stats.value = {
      projectCount: Number(data.projectCount) || 0,
      knowledgeDocumentCount: Number(data.knowledgeDocumentCount) || 0,
      evidenceCount: Number(data.evidenceCount) || 0,
      activeRuns: Number(data.activeRuns) || 0,
      pendingApprovals: Number(data.pendingApprovals) || 0,
      failedIngestJobCount: Number(data.failedIngestJobCount) || 0,
      failedSyncJobCount: Number(data.failedSyncJobCount) || 0
    }
    recentRuns.value = data.recentRuns || []
    recentSyncJobs.value = data.recentSyncJobs || []
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-hero,
.panel,
.stat-card {
  background: #ffffff;
  border: 1px solid #dce4ee;
  border-radius: 4px;
}

.page-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  padding: 24px;
}

.eyebrow {
  color: #426fa6;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.page-hero h2 {
  color: #1f2d3d;
  font-size: 26px;
  line-height: 1.2;
  margin: 6px 0 8px;
}

.page-hero p {
  max-width: 720px;
  color: #607184;
  margin: 0;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.stat-row {
  row-gap: 16px;
}

.stat-card {
  padding: 18px;
  min-height: 124px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.stat-label {
  color: #607184;
  font-size: 13px;
  font-weight: 700;
}

.stat-card strong {
  color: #1f2d3d;
  font-size: 32px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.stat-hint {
  color: #8b9aaa;
  font-size: 12px;
  line-height: 1.5;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: 0.9fr 1.2fr;
  gap: 18px;
}

.panel {
  padding: 20px;
}

.work-panel {
  grid-row: span 2;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-head h3 {
  color: #1f2d3d;
  font-size: 18px;
  margin: 3px 0 0;
}

.panel-head a {
  color: #607184;
  font-size: 13px;
  text-decoration: none;
}

.panel-head a:hover {
  color: #426fa6;
}

.todo-list,
.record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.todo-item,
.record-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px;
  border: 1px solid #dce4ee;
  border-radius: 4px;
  color: inherit;
  text-decoration: none;
}

.todo-item:hover,
.record-row:hover {
  border-color: #426fa6;
  background: #f8fafc;
}

.todo-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  margin-top: 8px;
  flex-shrink: 0;
}

.todo-dot.warning { background: #e6a23c; }
.todo-dot.primary { background: #426fa6; }
.todo-dot.danger { background: #f56c6c; }

.todo-item div,
.record-row div {
  min-width: 0;
}

.todo-item strong,
.record-row strong {
  color: #1f2d3d;
  display: block;
  font-size: 16px;
}

.todo-item p,
.record-row span {
  color: #607184;
  font-size: 13px;
  margin: 4px 0 0;
  line-height: 1.55;
}

.record-row em {
  flex-shrink: 0;
  border-radius: 3px;
  color: #426fa6;
  background: #eef3f8;
  font-style: normal;
  font-size: 12px;
  padding: 3px 8px;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .page-hero {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
