<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Project Directory</span>
        <h2>项目目录</h2>
        <p>后台只维护平台侧可见性：项目源、同步状态、证据覆盖和最近运行情况。项目接入、分析启动和业务审批在前台工作台完成。</p>
      </div>
      <el-button @click="fetchProjects">刷新</el-button>
    </section>

    <el-table :data="projects" v-loading="loading" stripe class="data-table">
      <el-table-column prop="projectKey" label="项目 Key" width="130" />
      <el-table-column prop="name" label="项目" min-width="180" />
      <el-table-column prop="repositoryType" label="来源" width="110" />
      <el-table-column prop="repositoryUrl" label="仓库地址" min-width="260" show-overflow-tooltip />
      <el-table-column prop="syncStatus" label="源状态" width="130">
        <template #default="{ row }">
          <el-tag effect="plain">{{ row.syncStatus || 'PENDING' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="evidenceCount" label="证据" width="90" />
      <el-table-column prop="runCount" label="Run" width="90" />
      <el-table-column prop="openRisks" label="待审批" width="100" />
      <el-table-column prop="lastSyncAt" label="最近同步" width="170">
        <template #default="{ row }">{{ formatDate(row.lastSyncAt) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getProjects } from '../api/index.js'

const loading = ref(false)
const projects = ref([])

onMounted(fetchProjects)

async function fetchProjects() {
  loading.value = true
  try {
    const response = await getProjects()
    projects.value = response.data.data || []
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  return value ? String(value).substring(0, 16) : '-'
}
</script>

<style scoped>
/* Hallmark | macrostructure: Admin Directory | tone: restrained operations | anchor hue: ink blue */
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px; background: #ffffff; border: 1px solid #dce4ee; border-radius: 4px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 760px; margin: 0; color: #607184; line-height: 1.7; }
.data-table { border: 1px solid #dce4ee; border-radius: 4px; }
@media (max-width: 720px) { .page-head { align-items: flex-start; flex-direction: column; } }
</style>
