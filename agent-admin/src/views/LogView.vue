<template>
  <div class="log-page">
    <div class="page-head">
      <h2 class="page-title">操作日志</h2>
      <p class="page-desc">记录所有后台管理操作，用于审计追溯</p>
    </div>

    <div class="filter-bar">
      <el-radio-group v-model="filterType" @change="fetchData" size="small">
        <el-radio-button :value="null">全部</el-radio-button>
        <el-radio-button value="CREATE">新增</el-radio-button>
        <el-radio-button value="UPDATE">修改</el-radio-button>
        <el-radio-button value="DELETE">删除</el-radio-button>
        <el-radio-button value="OTHER">其他</el-radio-button>
      </el-radio-group>
    </div>

    <el-table :data="logs" v-loading="loading" stripe class="log-table">
      <el-table-column prop="id" label="ID" width="60" align="center" />
      <el-table-column prop="username" label="操作人" width="100" />
      <el-table-column prop="ip" label="IP" width="130" />
      <el-table-column label="操作类型" width="90" align="center">
        <template #default="{ row }">
          <span :class="['type-tag', row.type]">{{ typeText(row.type) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="operation" label="操作描述" min-width="140" show-overflow-tooltip />
      <el-table-column prop="methodName" label="方法" min-width="180" show-overflow-tooltip />
      <el-table-column prop="args" label="请求参数" min-width="160" show-overflow-tooltip />
      <el-table-column prop="executionTime" label="耗时" width="80" align="center">
        <template #default="{ row }">
          <span :class="timeClass(row.executionTime)">{{ row.executionTime }}ms</span>
        </template>
      </el-table-column>
      <el-table-column prop="createTime" label="操作时间" width="160" align="center">
        <template #default="{ row }">
          {{ row.createTime ? row.createTime.substring(0, 19) : '' }}
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-wrap" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchData"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getOperationLogs } from '../api/index.js'

const logs = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)
const filterType = ref(null)

function typeText(t) {
  const map = { CREATE: '新增', UPDATE: '修改', DELETE: '删除', OTHER: '其他' }
  return map[t] || t
}

function timeClass(ms) {
  if (ms == null) return ''
  if (ms < 100) return 'time-fast'
  if (ms < 500) return 'time-normal'
  return 'time-slow'
}

async function fetchData() {
  loading.value = true
  try {
    const params = { page: page.value, size: pageSize }
    if (filterType.value) params.type = filterType.value
    const res = await getOperationLogs(params)
    logs.value = res.data.data.records
    total.value = res.data.data.total
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchData())
</script>

<style scoped>
.log-page { max-width: 1200px; }

.page-head { margin-bottom: 20px; }
.page-title { font-size: 20px; font-weight: 600; color: #303133; margin: 0 0 6px; }
.page-desc { font-size: 13px; color: #909399; margin: 0; }

.filter-bar { margin-bottom: 16px; }

.type-tag {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 12px; font-weight: 500;
}
.type-tag.CREATE { background: #e6f7e6; color: #10b981; }
.type-tag.UPDATE { background: #ecf5ff; color: #426fa6; }
.type-tag.DELETE { background: #fef0f0; color: #f56c6c; }
.type-tag.OTHER { background: #f5f7fa; color: #909399; }

.time-fast { color: #10b981; font-weight: 500; }
.time-normal { color: #e6a23c; font-weight: 500; }
.time-slow { color: #f56c6c; font-weight: 500; }

.pagination-wrap { margin-top: 20px; display: flex; justify-content: flex-end; }
</style>
