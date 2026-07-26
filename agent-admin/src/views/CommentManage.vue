<template>
  <div class="comment-manage">
    <div class="page-header">
      <h3 class="page-title">留言管理</h3>
      <div class="toolbar">
        <div class="filter-group">
          <span class="filter-label">类型:</span>
          <el-radio-group v-model="filterType" @change="fetchData" size="small">
            <el-radio-button :value="null">全部</el-radio-button>
            <el-radio-button :value="1">文章评论</el-radio-button>
            <el-radio-button :value="0">留言板</el-radio-button>
          </el-radio-group>
        </div>
        <div class="filter-group">
          <span class="filter-label">状态:</span>
          <el-radio-group v-model="filterStatus" @change="fetchData" size="small">
            <el-radio-button :value="null">全部</el-radio-button>
            <el-radio-button :value="1">通过</el-radio-button>
            <el-radio-button :value="0">待审</el-radio-button>
            <el-radio-button :value="-1">拒绝</el-radio-button>
          </el-radio-group>
        </div>
      </div>
    </div>

    <div class="table-container">
      <el-table :data="comments" v-loading="loading" stripe class="data-table">
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="author" label="作者" width="120">
          <template #default="{ row }">
            <span class="author-cell">{{ row.author }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="content-cell">{{ row.content }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.parentId != null" class="type-reply">回复</span>
            <span v-else>{{ row.articleId != null ? '文章' : '留言板' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <span class="status-badge" :class="statusClass(row.status)">
              {{ statusText(row.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="time-cell">{{ row.createTime ? row.createTime.substring(0, 16) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" align="center">
          <template #default="{ row }">
            <div class="actions">
              <button v-if="row.status !== 1" class="action-btn approve" @click="doUpdateStatus(row.id, 1)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
                通过
              </button>
              <button v-if="row.status !== -1" class="action-btn reject" @click="doUpdateStatus(row.id, -1)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                拒绝
              </button>
              <el-popconfirm title="确定删除？" @confirm="doDelete(row.id)">
                <template #reference>
                  <button class="action-btn del" @click.stop>
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    删除
                  </button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="pagination" v-if="total > pageSize">
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="fetchData" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getAdminComments, updateCommentStatus, deleteComment } from '../api/index.js'

const comments = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)
const filterStatus = ref(null)
const filterType = ref(null)

onMounted(() => fetchData())

function statusClass(s) { return s === 1 ? 'approved' : s === 0 ? 'pending' : 'rejected' }
function statusText(s) { return s === 1 ? '已通过' : s === 0 ? '待审核' : '已拒绝' }

async function fetchData() {
  loading.value = true
  try {
    const params = { page: page.value, size: pageSize }
    if (filterStatus.value !== null) params.status = filterStatus.value
    if (filterType.value !== null) params.type = filterType.value
    const res = await getAdminComments(params)
    comments.value = res.data.data.records
    total.value = res.data.data.total
  } finally {
    loading.value = false
  }
}

async function doUpdateStatus(id, status) {
  await updateCommentStatus(id, { status })
  fetchData()
}

async function doDelete(id) {
  await deleteComment(id)
  fetchData()
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }
.toolbar { display: flex; align-items: center; }
.filter-group { display: flex; align-items: center; gap: 10px; }
.filter-label { font-size: 12px; color: #909399; }

.table-container {
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 12px; overflow: hidden;
}

.author-cell { color: #303133; font-weight: 500; }
.content-cell { color: #606266; }
.time-cell { font-size: 12px; color: #909399; }

.status-badge {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: 500;
  padding: 2px 10px; border-radius: 4px;
}
.status-badge.approved { color: #67c23a; background: #f0f9eb; }
.status-badge.pending { color: #e6a23c; background: #fdf6ec; }
.status-badge.rejected { color: #f56c6c; background: #fef0f0; }

.actions { display: flex; gap: 5px; justify-content: center; }
.action-btn {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 4px 8px; border-radius: 5px; border: 1px solid transparent;
  font-size: 11px; cursor: pointer;
  transition: all 0.2s; background: none;
}
.action-btn.approve { color: #67c23a; border-color: #e1f3d8; }
.action-btn.approve:hover { background: #f0f9eb; border-color: #67c23a; transform: translateY(-1px); }
.action-btn.reject { color: #e6a23c; border-color: #faecd8; }
.action-btn.reject:hover { background: #fdf6ec; border-color: #e6a23c; transform: translateY(-1px); }
.action-btn.del { color: #f56c6c; border-color: #fde2e2; }
.action-btn.del:hover { background: #fef0f0; border-color: #f56c6c; transform: translateY(-1px); }

.pagination { margin-top: 20px; display: flex; justify-content: flex-end; }
</style>
