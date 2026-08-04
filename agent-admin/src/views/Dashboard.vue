<template>
  <div class="dashboard">
    <section class="page-hero">
      <div>
        <span class="eyebrow">ContractOps</span>
        <h2>合同 Agent 控制台</h2>
        <p>集中查看合同案件、审查发现、Agent Run、履约义务和审批状态。</p>
      </div>
      <div class="hero-actions">
        <el-button @click="$router.push('/agent-runs')">查看 Run</el-button>
        <el-button type="primary" @click="$router.push('/rules')">审查规则</el-button>
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
              <strong>{{ run.subjectType === 'CONTRACT_CASE' ? '合同 #'+run.subjectId : (run.projectName || 'Run #'+run.id) }}</strong>
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
            <span class="eyebrow">Documents</span>
            <h3>最近上传文件</h3>
          </div>
          <router-link to="/evidence-sync">全部</router-link>
        </div>
        <div class="record-list" v-loading="loading">
          <div v-for="doc in recentDocs" :key="doc.id" class="record-row">
            <div>
              <strong>{{ doc.fileName || 'Document #'+doc.id }}</strong>
              <span>{{ doc.caseKey || '' }} · {{ doc.parseStatus }}</span>
            </div>
            <em>{{ doc.documentType }}</em>
          </div>
          <el-empty v-if="!loading && recentDocs.length === 0" description="暂无上传文件" :image-size="72" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getContractPortfolio, getAgentRuns, getKbDocuments } from '../api/index.js'
import api from '../api/index.js'

const loading = ref(false)
const stats = ref({
  totalCases: 0, pendingReview: 0, pendingApproval: 0,
  inFulfillment: 0, expiringSoon: 0, overdue: 0,
  obligationsTotal: 0, obligationsOverdue: 0, openFindings: 0,
  activeRuns: 0, totalAmount: 0
})
const recentRuns = ref([])
const recentDocs = ref([])

const statItems = computed(() => [
  { label: '合同案件', value: stats.value.totalCases, hint: '合同全生命周期案件' },
  { label: '待审查', value: stats.value.pendingReview, hint: '等待 Agent 审查或人工复核' },
  { label: '待审批', value: stats.value.pendingApproval, hint: '需要法务/管理层审批' },
  { label: '履约中', value: stats.value.inFulfillment, hint: '已签署正在执行中' },
  { label: '即将到期', value: stats.value.expiringSoon, hint: '30 天内到期需关注' },
  { label: '活跃 Run', value: stats.value.activeRuns, hint: '正在执行的 Agent 分析' },
  { label: '待处理发现', value: stats.value.openFindings, hint: '审查发现待修改或接受' },
  { label: '逾期义务', value: stats.value.obligationsOverdue, hint: '已逾期的履约义务' }
])

onMounted(fetchDashboard)

async function fetchDashboard() {
  loading.value = true
  try {
    // Contract portfolio
    const pf = await getContractPortfolio()
    const d = pf.data.data || {}
    Object.assign(stats.value, {
      totalCases: d.total || 0, pendingReview: d.pendingReview || 0,
      pendingApproval: d.pendingApproval || 0, inFulfillment: d.inFulfillment || 0,
      expiringSoon: d.expiringSoon || 0, overdue: d.overdue || 0,
      obligationsTotal: d.obligationsTotal || 0, obligationsOverdue: d.obligationsOverdue || 0,
      openFindings: d.openFindings || 0, activeRuns: d.activeRuns || 0,
      totalAmount: d.totalAmount || 0
    })
  } catch {}

  try {
    const runs = await getAgentRuns()
    recentRuns.value = (runs.data.data || []).slice(0, 5)
  } catch {}

  try {
    const docs = await api.get('/api/admin/contracts/documents')
    recentDocs.value = (docs.data.data || []).slice(0, 5)
  } catch {}
  finally { loading.value = false }
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
