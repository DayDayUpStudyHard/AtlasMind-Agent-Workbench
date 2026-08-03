<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">项目数据同步</span>
        <h2>项目数据同步</h2>
        <p>把 GitHub、本地项目、Jira/禅道、CI/CD 里的项目资料同步进来，作为 Agent 分析项目、生成报告和展示引用来源的依据。</p>
      </div>
      <el-button @click="fetchProjects">刷新</el-button>
    </section>

    <div class="project-grid" v-loading="loading">
      <section v-for="project in projects" :key="project.id" class="project-card">
        <div class="card-head">
          <div>
            <span>{{ project.projectKey }}</span>
            <h3>{{ project.name }}</h3>
          </div>
          <el-tag effect="plain">{{ syncLabel(project.syncStatus) }}</el-tag>
        </div>
        <p>{{ project.repositoryUrl || '暂未配置仓库地址' }}</p>
        <div class="card-meta">
          <span>已入库资料 {{ project.evidenceCount || 0 }}</span>
          <span>最近同步 {{ formatDate(project.lastSyncAt) }}</span>
        </div>
      </section>
    </div>

    <section class="connector-strip">
      <article v-for="item in connectors" :key="item.name">
        <strong>{{ item.name }}</strong>
        <span>{{ item.status }}</span>
        <p>{{ item.note }}</p>
      </article>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getContracts } from '../api/index.js'

const loading = ref(false)
const projects = ref([])
const connectors = [
  { name: 'GitHub', status: '已接入', note: '同步 README、文件树、Issue、PR 和 Commit，给项目健康分析提供依据。' },
  { name: '本地项目', status: '接口预留', note: '后续接入本地目录扫描、技术文档和依赖分析。' },
  { name: 'Jira / 禅道', status: '接口预留', note: '后续接入需求、缺陷、迭代和负责人数据。' },
  { name: 'CI/CD', status: '接口预留', note: '后续接入构建、测试、发布和失败记录。' }
]

onMounted(fetchProjects)

async function fetchProjects() {
  loading.value = true
  try {
    projects.value = (await getContracts()).data.data || []
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  return value ? String(value).substring(0, 16) : '-'
}
function syncLabel(status) {
  return { READY: '已同步', SYNCING: '同步中', FAILED: '同步失败', PENDING: '待同步' }[status] || '待同步'
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head, .project-card, .connector-strip article {
  background: #ffffff;
  border: 1px solid #dce4ee;
  border-radius: 4px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 22px;
}
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p, .project-card p, .connector-strip p { margin: 0; color: #607184; line-height: 1.7; }
.project-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.project-card { min-width: 0; padding: 18px; }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.card-head span { color: #426fa6; font-size: 12px; font-weight: 800; }
.card-head h3 { margin: 6px 0 12px; color: #1f2d3d; font-size: 18px; }
.card-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 14px; color: #8b9aaa; font-size: 12px; }
.card-actions { margin-top: 16px; }
.connector-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.connector-strip article { padding: 16px; }
.connector-strip strong { display: block; color: #1f2d3d; }
.connector-strip span { display: inline-block; margin: 8px 0; color: #426fa6; font-size: 12px; font-weight: 800; }
@media (max-width: 1100px) { .project-grid, .connector-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { .project-grid, .connector-strip { grid-template-columns: 1fr; } .page-head { align-items: flex-start; flex-direction: column; } }
</style>
