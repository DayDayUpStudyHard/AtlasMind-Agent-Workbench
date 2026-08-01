<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Agent Runs</span>
        <h2>Agent 运行记录</h2>
        <p>追踪每次分析任务的项目、问题、执行阶段、进度和生成结果，避免系统变成不可解释的黑箱。</p>
      </div>
      <el-button @click="fetchRuns">刷新</el-button>
    </section>

    <el-table :data="runs" v-loading="loading" stripe class="data-table">
      <el-table-column prop="id" label="Run ID" width="90" />
      <el-table-column prop="projectName" label="项目" min-width="170" />
      <el-table-column prop="runType" label="任务类型" width="140">
        <template #default="{ row }">{{ runTypeLabel(row.runType) }}</template>
      </el-table-column>
      <el-table-column prop="question" label="问题" min-width="260" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="150" />
      <el-table-column prop="progress" label="进度" width="180">
        <template #default="{ row }">
          <el-progress :percentage="Number(row.progress) || 0" :stroke-width="8" />
        </template>
      </el-table-column>
      <el-table-column prop="currentStep" label="当前步骤" min-width="180" />
      <el-table-column prop="createTime" label="创建时间" width="170">
        <template #default="{ row }">{{ formatDate(row.createTime) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110" fixed="right">
        <template #default="{ row }">
          <el-button
            type="danger"
            link
            :disabled="isRunning(row.status)"
            @click="removeRun(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteAgentRun, getAgentRuns } from '../api/index.js'

const loading = ref(false)
const runs = ref([])

onMounted(fetchRuns)

async function fetchRuns() {
  loading.value = true
  try {
    runs.value = (await getAgentRuns()).data.data || []
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  return value ? String(value).substring(0, 16) : '-'
}

function isRunning(status) {
  return ['CREATED', 'CONTEXT_BUILDING', 'ANALYZING', 'VERIFYING', 'PLANNING'].includes(status)
}

function runTypeLabel(type) {
  return { HEALTH_ANALYSIS: '健康分析', PROJECT_ONBOARDING: '项目接手', ENGINEERING_DECISION: '研发决策' }[type] || type || 'Agent 任务'
}

async function removeRun(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除 Agent Run #${row.id} 吗？关联步骤、报告和动作也会一起删除。`,
      '删除运行记录',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await deleteAgentRun(row.id)
    ElMessage.success('运行记录已删除')
    await fetchRuns()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.message || '删除运行记录失败')
  }
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { margin: 0; color: #607184; line-height: 1.7; }
.data-table { border: 1px solid #dce4ee; border-radius: 4px; }
@media (max-width: 720px) { .page-head { align-items: flex-start; flex-direction: column; } }
</style>
