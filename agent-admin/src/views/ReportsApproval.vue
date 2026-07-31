<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">报告与动作状态</span>
        <h2>报告与动作状态</h2>
        <p>后台查看 Agent 报告、业务审批队列和外部动作执行结果。审批决定由项目前台的负责人完成，后台只处理阻塞与审计。</p>
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
              <p>{{ report.projectName }} / {{ healthLabel(report.healthStatus) }} / {{ report.healthScore }}/100</p>
            </div>
            <el-tag effect="plain">{{ reportStatusLabel(report.status) }}</el-tag>
          </article>
          <el-empty v-if="!loading && reports.length === 0" description="暂无报告" :image-size="72" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <h3>动作队列</h3>
          <span>{{ actions.length }} 条</span>
        </div>
        <div class="record-list" v-loading="loading">
          <article v-for="action in actions" :key="action.id" class="record-row">
            <div>
              <strong>{{ action.title }}</strong>
              <p>{{ action.projectName }} / {{ actionTypeLabel(action.actionType) }}</p>
              <small v-if="action.errorMessage">{{ action.errorMessage }}</small>
            </div>
            <el-tag :type="tagType(action.status)" effect="plain">{{ actionStatusLabel(action.status) }}</el-tag>
          </article>
          <el-empty v-if="!loading && actions.length === 0" description="暂无动作" :image-size="72" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getAgentActions, getAgentReports } from '../api/index.js'

const loading = ref(false)
const reports = ref([])
const actions = ref([])

onMounted(fetchData)

async function fetchData() {
  loading.value = true
  try {
    const [reportResponse, actionResponse] = await Promise.all([
      getAgentReports(),
      getAgentActions()
    ])
    reports.value = reportResponse.data.data || []
    actions.value = actionResponse.data.data || []
  } finally {
    loading.value = false
  }
}

function tagType(status) {
  return { EXECUTED: 'success', BLOCKED: 'danger', REJECTED: 'info', PENDING_APPROVAL: 'warning' }[status] || 'info'
}
function healthLabel(status) {
  return { HEALTHY: '稳定', WATCH: '关注', AT_RISK: '有风险', UNKNOWN: '未分析' }[status] || '未分析'
}
function reportStatusLabel(status) {
  return { DRAFT: '草稿', PUBLISHED: '已发布', ARCHIVED: '已归档' }[status] || status || '未知'
}
function actionTypeLabel(type) {
  return { CREATE_GITHUB_ISSUE: '创建 GitHub Issue' }[type] || type || '外部动作'
}
function actionStatusLabel(status) {
  return { EXECUTED: '已执行', BLOCKED: '执行阻塞', REJECTED: '已驳回', PENDING_APPROVAL: '待审批', APPROVED: '已批准' }[status] || status || '未知'
}
</script>

<style scoped>
/* Hallmark | macrostructure: Admin Review Queue | tone: auditable operations | anchor hue: ink blue */
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head, .panel { background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 780px; margin: 0; color: #607184; line-height: 1.7; }
.split-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.panel { min-width: 0; padding: 18px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.panel-head h3 { margin: 0; color: #1f2d3d; font-size: 18px; }
.panel-head span { color: #8b9aaa; font-size: 12px; }
.record-list { display: flex; flex-direction: column; gap: 10px; }
.record-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px; border: 1px solid #dce4ee; border-radius: 4px; }
.record-row div { min-width: 0; }
.record-row strong { color: #1f2d3d; overflow-wrap: anywhere; }
.record-row p { margin: 5px 0 0; color: #607184; font-size: 13px; line-height: 1.55; }
.record-row small { display: block; margin-top: 6px; color: #b35c56; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
@media (max-width: 980px) { .split-grid { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .page-head, .record-row { align-items: flex-start; flex-direction: column; } }
</style>
