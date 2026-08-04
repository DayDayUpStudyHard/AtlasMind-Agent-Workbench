<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Contract Registry</span>
        <h2>合同管理</h2>
        <p>管理合同案件主数据。删除采用软删除：用户端隐藏案件，但文档、审查报告、Agent 轨迹和证据链会继续保留，便于审计和恢复。</p>
      </div>
      <el-button @click="fetchCases">刷新</el-button>
    </section>

    <section class="toolbar">
      <el-input
        v-model="filters.keyword"
        clearable
        placeholder="搜索案件编号、标题或相对方"
        class="keyword-input"
        @clear="resetToFirstPage"
        @keyup.enter="resetToFirstPage"
      />
      <el-select v-model="filters.status" clearable placeholder="全部状态" class="status-select" @change="resetToFirstPage">
        <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-segmented v-model="filters.deletedMode" :options="deletedOptions" @change="resetToFirstPage" />
    </section>

    <el-table :data="cases" v-loading="loading" stripe class="data-table">
      <el-table-column prop="caseKey" label="案件编号" width="150" show-overflow-tooltip />
      <el-table-column label="合同信息" min-width="260">
        <template #default="{ row }">
          <div class="case-cell">
            <strong>{{ row.title || '-' }}</strong>
            <span>{{ row.counterparty || '未填写相对方' }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" effect="plain">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="contractType" label="类型" width="150" show-overflow-tooltip />
      <el-table-column label="金额" width="150" align="right">
        <template #default="{ row }">{{ formatAmount(row) }}</template>
      </el-table-column>
      <el-table-column label="证据链" width="210">
        <template #default="{ row }">
          <div class="count-strip">
            <span>{{ Number(row.documentCount) || 0 }} 文档</span>
            <span>{{ Number(row.runCount) || 0 }} 运行</span>
            <span>{{ Number(row.reportCount) || 0 }} 报告</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="风险" width="120">
        <template #default="{ row }">
          <el-tag :type="Number(row.openFindingCount) > 0 ? 'danger' : 'success'" effect="plain">
            {{ Number(row.openFindingCount) || 0 }} 未处理
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="updateTime" label="更新时间" width="170">
        <template #default="{ row }">{{ formatDate(row.updateTime) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="!isDeletedView"
            type="danger"
            link
            @click="openDeleteImpact(row)"
          >删除</el-button>
          <el-button
            v-else
            type="primary"
            link
            @click="restoreCase(row)"
          >恢复</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-row">
      <span>共 {{ total }} 条</span>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="sizes, prev, pager, next"
        @size-change="resetToFirstPage"
        @current-change="fetchCases"
      />
    </div>

    <el-dialog v-model="impactDialogVisible" title="删除合同案件" width="560px">
      <div v-loading="impactLoading" class="impact-body">
        <template v-if="deleteImpact">
          <div class="impact-title">
            <strong>{{ deleteImpact.caseKey }} · {{ deleteImpact.title }}</strong>
            <el-tag :type="statusTagType(deleteImpact.status)" effect="plain">{{ statusLabel(deleteImpact.status) }}</el-tag>
          </div>
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="本次操作只会隐藏合同案件，不会删除文档、报告、Agent 运行轨迹和证据链。"
          />
          <div class="impact-grid">
            <div v-for="item in impactItems" :key="item.key" class="impact-item">
              <span>{{ item.label }}</span>
              <strong>{{ Number(deleteImpact[item.key]) || 0 }}</strong>
            </div>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="impactDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="deleting" :disabled="impactLoading" @click="confirmDelete">确认删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteAdminContractCase,
  getAdminContractCases,
  getAdminContractDeleteImpact,
  restoreAdminContractCase
} from '../api/index.js'

const loading = ref(false)
const impactLoading = ref(false)
const deleting = ref(false)
const cases = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const selectedCase = ref(null)
const deleteImpact = ref(null)
const impactDialogVisible = ref(false)

const filters = reactive({
  keyword: '',
  status: '',
  deletedMode: 'active'
})

const deletedOptions = [
  { label: '正常案件', value: 'active' },
  { label: '已删除', value: 'deleted' }
]

const statusOptions = [
  { label: '草稿', value: 'DRAFT' },
  { label: '录入解析中', value: 'INTAKE_PARSING' },
  { label: '待确认录入', value: 'INTAKE_CONFIRMING' },
  { label: '材料待补充', value: 'MATERIAL_PENDING' },
  { label: '待审查', value: 'READY_FOR_REVIEW' },
  { label: '审查中', value: 'REVIEWING' },
  { label: '需修订', value: 'NEEDS_REVISION' },
  { label: '待审批', value: 'PENDING_APPROVAL' },
  { label: '已批准', value: 'APPROVED' },
  { label: '待签署', value: 'READY_TO_SIGN' },
  { label: '已签署', value: 'SIGNED' },
  { label: '履约中', value: 'IN_FULFILLMENT' },
  { label: '已到期', value: 'EXPIRED' },
  { label: '已终止', value: 'TERMINATED' }
]

const impactItems = [
  { key: 'documentCount', label: '合同文档' },
  { key: 'clauseCount', label: '解析条款' },
  { key: 'chunkCount', label: '检索切片' },
  { key: 'timelineNodeCount', label: '时间节点' },
  { key: 'openFindingCount', label: '未处理发现' },
  { key: 'runCount', label: 'Agent Run' },
  { key: 'reportCount', label: 'Agent 报告' },
  { key: 'actionCount', label: 'Agent 动作' }
]

const isDeletedView = computed(() => filters.deletedMode === 'deleted')

onMounted(fetchCases)

async function fetchCases() {
  loading.value = true
  try {
    const response = await getAdminContractCases({
      page: page.value,
      size: size.value,
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
      deleted: isDeletedView.value
    })
    const data = response.data.data || {}
    cases.value = data.records || []
    total.value = Number(data.total) || 0
  } finally {
    loading.value = false
  }
}

function resetToFirstPage() {
  page.value = 1
  fetchCases()
}

async function openDeleteImpact(row) {
  selectedCase.value = row
  deleteImpact.value = null
  impactDialogVisible.value = true
  impactLoading.value = true
  try {
    deleteImpact.value = (await getAdminContractDeleteImpact(row.id)).data.data
  } catch (error) {
    impactDialogVisible.value = false
    ElMessage.error(error.response?.data?.message || '读取删除影响失败')
  } finally {
    impactLoading.value = false
  }
}

async function confirmDelete() {
  if (!selectedCase.value) return
  deleting.value = true
  try {
    await deleteAdminContractCase(selectedCase.value.id)
    ElMessage.success('合同案件已删除，可在已删除视图中恢复')
    impactDialogVisible.value = false
    await fetchCases()
  } catch (error) {
    ElMessage.error(error.response?.data?.message || '删除合同案件失败')
  } finally {
    deleting.value = false
  }
}

async function restoreCase(row) {
  try {
    await ElMessageBox.confirm(
      `确定恢复合同案件 ${row.caseKey || '#' + row.id} 吗？恢复后用户端会重新显示该案件。`,
      '恢复合同案件',
      { type: 'warning', confirmButtonText: '恢复', cancelButtonText: '取消' }
    )
    await restoreAdminContractCase(row.id)
    ElMessage.success('合同案件已恢复')
    await fetchCases()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.response?.data?.message || '恢复合同案件失败')
  }
}

function formatDate(value) {
  return value ? String(value).substring(0, 16) : '-'
}

function formatAmount(row) {
  if (row.amount === null || row.amount === undefined || row.amount === '') return '-'
  const amount = Number(row.amount)
  if (Number.isNaN(amount)) return `${row.currency || ''} ${row.amount}`
  return `${row.currency || 'CNY'} ${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function statusLabel(status) {
  return Object.fromEntries(statusOptions.map(item => [item.value, item.label]))[status] || status || '未知'
}

function statusTagType(status) {
  return {
    READY_FOR_REVIEW: 'warning',
    INTAKE_PARSING: 'warning',
    INTAKE_CONFIRMING: 'warning',
    REVIEWING: 'warning',
    NEEDS_REVISION: 'danger',
    PENDING_APPROVAL: 'warning',
    APPROVED: 'success',
    SIGNED: 'success',
    IN_FULFILLMENT: 'success',
    EXPIRED: 'info',
    TERMINATED: 'info'
  }[status] || 'info'
}
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head, .toolbar { background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 22px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }
.toolbar { display: flex; align-items: center; gap: 12px; padding: 14px; }
.keyword-input { max-width: 360px; }
.status-select { width: 180px; }
.data-table { border: 1px solid #dce4ee; border-radius: 4px; }
.case-cell { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.case-cell strong { color: #1f2d3d; overflow-wrap: anywhere; }
.case-cell span { color: #607184; font-size: 12px; overflow-wrap: anywhere; }
.count-strip { display: flex; flex-wrap: wrap; gap: 6px; }
.count-strip span { padding: 2px 7px; border: 1px solid #dce4ee; border-radius: 4px; color: #607184; font-size: 12px; background: #fbfcfe; }
.pagination-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 2px 0; color: #607184; }
.impact-body { min-height: 260px; }
.impact-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.impact-title strong { color: #1f2d3d; line-height: 1.5; overflow-wrap: anywhere; }
.impact-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.impact-item { display: flex; flex-direction: column; gap: 6px; padding: 12px; border: 1px solid #dce4ee; border-radius: 4px; background: #fbfcfe; }
.impact-item span { color: #607184; font-size: 12px; }
.impact-item strong { color: #1f2d3d; font-size: 20px; }
@media (max-width: 860px) {
  .page-head, .toolbar, .pagination-row { align-items: flex-start; flex-direction: column; }
  .keyword-input, .status-select { width: 100%; max-width: none; }
  .impact-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
