<template>
  <div class="page">
    <div class="page-head">
      <div><h1>合同案件管理</h1><p>查看和管理所有合同案件、审查发现和履约状态</p></div>
      <span class="badge">{{ cases.length }} 个案件</span>
    </div>

    <el-table :data="cases" stripe v-loading="loading" @row-click="row => $router.push(`/contracts/${row.id}`)" style="cursor:pointer">
      <el-table-column prop="caseKey" label="案件编号" width="130" />
      <el-table-column prop="title" label="合同标题" min-width="200" show-overflow-tooltip />
      <el-table-column label="类型" width="110">
        <template #default="{row}">{{ typeLabel(row.contractType) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{row}"><el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="counterparty" label="相对方" width="150" />
      <el-table-column label="金额" width="120">
        <template #default="{row}">{{ row.amount ? (row.amount/10000).toFixed(0)+'万' : '—' }}</template>
      </el-table-column>
      <el-table-column prop="department" label="部门" width="100" />
      <el-table-column label="到期" width="110">
        <template #default="{row}">{{ row.expiryDate || '—' }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../api/index.js'

const cases = ref([])
const loading = ref(true)

onMounted(async () => {
  try { const r = await api.get('/api/workspace/contracts'); cases.value = r.data.data || [] }
  catch {}
  finally { loading.value = false }
})

function typeLabel(t) { return { SERVICE_PROCUREMENT:'服务采购', GOODS_PURCHASE:'货物采购', NDA:'保密协议' }[t] || t }
function statusLabel(s) { return { DRAFT:'草稿', READY_FOR_REVIEW:'待审查', REVIEWING:'审查中', PENDING_APPROVAL:'待审批', APPROVED:'已批准', SIGNED:'已签署', IN_FULFILLMENT:'履约中', EXPIRED:'已到期' }[s] || s }
function statusTag(s) { return { DRAFT:'info', READY_FOR_REVIEW:'warning', REVIEWING:'', PENDING_APPROVAL:'danger', APPROVED:'success', SIGNED:'success', IN_FULFILLMENT:'', EXPIRED:'warning' }[s] || '' }
</script>

<style scoped>
.page{padding:0}
.page-head{display:flex;justify-content:space-between;align-items:end;margin-bottom:20px}
.page-head h1{margin:0;font-size:24px;color:#1f2d3d}
.page-head p{margin:6px 0 0;color:#8b9aaa;font-size:13px}
.badge{padding:4px 12px;border:1px solid #dce4ee;border-radius:4px;background:#fff;color:#426fa6;font-size:12px;font-weight:800}
</style>
