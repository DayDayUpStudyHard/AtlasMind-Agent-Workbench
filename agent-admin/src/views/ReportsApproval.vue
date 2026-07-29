<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Reports & Approval</span>
        <h2>报告与审批</h2>
        <p>集中查看 Agent 生成的健康报告和待审批自动化动作，保留人工确认门禁。</p>
      </div>
      <el-button @click="fetchData">刷新</el-button>
    </section>

    <div class="split-grid">
      <section class="panel">
        <div class="panel-head">
          <h3>最新报告</h3>
          <span>{{ reports.length }} 条</span>
        </div>
        <div class="record-list" v-loading="loading">
          <article v-for="report in reports" :key="report.id" class="record-row">
            <div>
              <strong>{{ report.title }}</strong>
              <p>{{ report.projectName }} · {{ report.healthStatus }} · {{ report.healthScore }}/100</p>
            </div>
            <el-tag effect="plain">{{ report.status }}</el-tag>
          </article>
          <el-empty v-if="!loading && reports.length === 0" description="暂无报告" :image-size="72" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>待审批动作</h3>
          <span>{{ actions.length }} 条</span>
        </div>
        <div class="record-list" v-loading="loading">
          <article v-for="action in actions" :key="action.id" class="record-row">
            <div>
              <strong>{{ action.title }}</strong>
              <p>{{ action.projectName }} · {{ action.actionType }}</p>
            </div>
            <div class="action-buttons">
              <el-button size="small" @click="reject(action)">驳回</el-button>
              <el-button size="small" type="primary" @click="approve(action)">通过</el-button>
            </div>
          </article>
          <el-empty v-if="!loading && actions.length === 0" description="暂无待审批动作" :image-size="72" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { approveProjectAction, getProject, getProjectRun, getProjects } from '../api/index.js'

const loading = ref(false)
const reports = ref([])
const actions = ref([])

onMounted(fetchData)

async function fetchData() {
  loading.value = true
  try {
    const projectRows = (await getProjects()).data.data || []
    const details = await Promise.all(projectRows.map(project => getProject(project.id)))
    const reportRows = []
    const actionRows = []
    for (const response of details) {
      const project = response.data.data || {}
      for (const report of project.reports || []) reportRows.push({ ...report, projectName: project.name })
      for (const run of (project.runs || []).slice(0, 5)) {
        const runResponse = await getProjectRun(run.id)
        const runData = runResponse.data.data || {}
        for (const action of runData.actions || []) {
          if (action.status === 'PENDING_APPROVAL') actionRows.push({ ...action, projectName: project.name })
        }
      }
    }
    reports.value = reportRows.sort((a, b) => Number(b.id) - Number(a.id))
    actions.value = actionRows.sort((a, b) => Number(b.id) - Number(a.id))
  } finally {
    loading.value = false
  }
}

async function approve(action) {
  await approveProjectAction(action.runId, action.id, { approved: true, approvedBy: 'admin' })
  ElMessage.success('审批已通过')
  await fetchData()
}

async function reject(action) {
  await approveProjectAction(action.runId, action.id, { approved: false, approvedBy: 'admin' })
  ElMessage.success('审批已驳回')
  await fetchData()
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head, .panel { background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { margin: 0; color: #607184; line-height: 1.7; }
.split-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.panel { min-width: 0; padding: 18px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.panel-head h3 { margin: 0; color: #1f2d3d; font-size: 18px; }
.panel-head span { color: #8b9aaa; font-size: 12px; }
.record-list { display: flex; flex-direction: column; gap: 10px; }
.record-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px; border: 1px solid #dce4ee; border-radius: 4px; }
.record-row strong { color: #1f2d3d; }
.record-row p { margin: 5px 0 0; color: #607184; font-size: 13px; }
.action-buttons { display: flex; gap: 8px; flex-shrink: 0; }
@media (max-width: 980px) { .split-grid { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .page-head, .record-row { align-items: flex-start; flex-direction: column; } }
</style>
