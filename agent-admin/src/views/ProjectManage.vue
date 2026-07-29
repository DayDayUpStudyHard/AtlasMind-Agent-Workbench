<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Projects</span>
        <h2>项目管理</h2>
        <p>维护研发项目、仓库来源、团队规模和交付目标，作为 Agent 分析的业务上下文入口。</p>
      </div>
      <el-button type="primary" @click="dialogOpen = true">新建项目</el-button>
    </section>

    <el-table :data="projects" v-loading="loading" stripe class="data-table">
      <el-table-column prop="projectKey" label="项目 Key" width="130" />
      <el-table-column prop="name" label="项目" min-width="180" />
      <el-table-column prop="repositoryType" label="来源" width="110" />
      <el-table-column prop="healthStatus" label="健康状态" width="120">
        <template #default="{ row }">
          <el-tag effect="plain">{{ row.healthStatus || 'UNKNOWN' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="healthScore" label="评分" width="90" />
      <el-table-column prop="evidenceCount" label="证据" width="90" />
      <el-table-column prop="runCount" label="Run" width="90" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="sync(row)">同步证据</el-button>
          <el-button size="small" type="primary" @click="run(row)">启动 Run</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" title="新建项目" width="560px">
      <el-form label-position="top">
        <el-form-item label="项目名称">
          <el-input v-model="form.name" placeholder="例如 AtlasMind Agent Workbench" />
        </el-form-item>
        <el-form-item label="项目 Key">
          <el-input v-model="form.projectKey" placeholder="例如 ATLASMIND" />
        </el-form-item>
        <el-form-item label="GitHub 仓库 URL">
          <el-input v-model="form.repositoryUrl" placeholder="https://github.com/org/repo" />
        </el-form-item>
        <el-form-item label="默认分支">
          <el-input v-model="form.defaultBranch" placeholder="main" />
        </el-form-item>
        <el-form-item label="业务范围">
          <el-input v-model="form.businessScope" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" @click="submitProject">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createProject, getProjects, startProjectRun, syncProjectEvidence } from '../api/index.js'

const loading = ref(false)
const dialogOpen = ref(false)
const projects = ref([])
const form = ref({
  name: '',
  projectKey: '',
  repositoryType: 'GITHUB',
  repositoryUrl: '',
  defaultBranch: 'main',
  businessScope: ''
})

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

async function submitProject() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  await createProject(form.value)
  ElMessage.success('项目已创建')
  dialogOpen.value = false
  form.value = { name: '', projectKey: '', repositoryType: 'GITHUB', repositoryUrl: '', defaultBranch: 'main', businessScope: '' }
  await fetchProjects()
}

async function sync(row) {
  await syncProjectEvidence(row.id)
  ElMessage.success('证据同步已触发')
  await fetchProjects()
}

async function run(row) {
  await startProjectRun(row.id)
  ElMessage.success('Agent Run 已启动')
  await fetchProjects()
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 22px;
  background: #ffffff;
  border: 1px solid #dce4ee;
  border-radius: 4px;
}

.eyebrow {
  color: #426fa6;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.page-head h2 {
  margin: 6px 0 8px;
  color: #1f2d3d;
  font-size: 24px;
}

.page-head p {
  margin: 0;
  color: #607184;
  line-height: 1.7;
}

.data-table {
  border: 1px solid #dce4ee;
  border-radius: 4px;
}

@media (max-width: 720px) {
  .page-head {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
