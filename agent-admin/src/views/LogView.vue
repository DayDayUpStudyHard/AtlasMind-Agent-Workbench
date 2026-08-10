<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Audit Trail</span>
        <h2>操作日志</h2>
        <p>记录所有后台管理操作，用于审计追溯</p>
      </div>
      <el-button @click="fetchData">刷新</el-button>
    </section>

    <section class="toolbar">
      <el-radio-group v-model="filterType" @change="onFilterChange" size="small">
        <el-radio-button :value="null">全部</el-radio-button>
        <el-radio-button value="CREATE">新增</el-radio-button>
        <el-radio-button value="UPDATE">修改</el-radio-button>
        <el-radio-button value="DELETE">删除</el-radio-button>
        <el-radio-button value="OTHER">其他</el-radio-button>
      </el-radio-group>
    </section>

    <el-table :data="logs" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="60" align="center" />
      <el-table-column prop="username" label="操作人" width="100" />
      <el-table-column prop="ip" label="IP" width="130" />
      <el-table-column label="操作类型" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="typeTagType(row.type)" effect="plain" size="small">{{ typeText(row.type) }}</el-tag>
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

    <div class="pagination-row" v-if="total > 0">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
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

function typeTagType(t) {
  const map = { CREATE: 'success', UPDATE: 'primary', DELETE: 'danger', OTHER: 'info' }
  return map[t] || 'info'
}

function timeClass(ms) {
  if (ms == null) return ''
  if (ms < 100) return 'time-fast'
  if (ms < 500) return 'time-normal'
  return 'time-slow'
}

function onFilterChange() {
  page.value = 1
  fetchData()
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
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }
.toolbar { display: flex; align-items: center; gap: 12px; padding: 14px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.pagination-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; color: #607184; }

.time-fast { color: #10b981; font-weight: 500; }
.time-normal { color: #e6a23c; font-weight: 500; }
.time-slow { color: #f56c6c; font-weight: 500; }
</style>
