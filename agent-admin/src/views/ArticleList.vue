<template>
  <div class="article-list">
    <div class="page-header">
      <h3 class="page-title">文章管理</h3>
      <div class="toolbar">
        <div class="filter-group">
          <span class="filter-label">筛选:</span>
          <el-select v-model="filterStatus" placeholder="状态" clearable @change="fetchData" class="filter-select" size="small">
            <el-option label="已发布" :value="1" />
            <el-option label="草稿" :value="0" />
          </el-select>
          <el-select v-model="filterVisibility" placeholder="可见性" clearable @change="fetchData" class="filter-select" size="small">
            <el-option label="公开" value="PUBLIC" />
            <el-option label="仅AI" value="RAG_ONLY" />
            <el-option label="私有" value="PRIVATE" />
          </el-select>
        </div>
        <el-button type="primary" @click="$router.push('/articles/create')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新建文章
        </el-button>
      </div>
    </div>

    <div class="table-container">
      <el-table :data="articles" v-loading="loading" stripe class="data-table">
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="title" label="标题" min-width="240">
          <template #default="{ row }">
            <span class="article-title">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <span class="status-badge" :class="row.status === 1 ? 'published' : 'draft'">
              {{ row.status === 1 ? '已发布' : '草稿' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="可见性" width="100" align="center">
          <template #default="{ row }">
            <span class="visibility-badge" :class="(row.visibility || 'PUBLIC').toLowerCase()">
              {{ visibilityLabel(row.visibility) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="viewCount" label="阅读" width="80" align="center">
          <template #default="{ row }">
            <span class="view-count">{{ row.viewCount }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="time-cell">{{ row.createTime ? row.createTime.substring(0, 16) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" align="center">
          <template #default="{ row }">
            <div class="actions">
              <button class="action-btn preview" @click="openPreview(row.id)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                预览
              </button>
              <button class="action-btn edit" @click="$router.push(`/articles/${row.id}/edit`)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <el-popconfirm title="确定删除？" @confirm="doDelete(row.id)">
                <template #reference>
                  <button class="action-btn delete" @click.stop>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
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
import { getAdminArticles, deleteArticle } from '../api/index.js'

const articles = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)
const filterStatus = ref(null)
const filterVisibility = ref(null)
const visibilityLabels = { PUBLIC: '公开', RAG_ONLY: '仅AI', PRIVATE: '私有' }
function visibilityLabel(v) { return visibilityLabels[v] || '公开' }

onMounted(() => fetchData())

async function fetchData() {
  loading.value = true
  try {
    const params = { page: page.value, size: pageSize }
    if (filterStatus.value !== null && filterStatus.value !== '') params.status = filterStatus.value
    if (filterVisibility.value && filterVisibility.value !== '') params.visibility = filterVisibility.value
    const res = await getAdminArticles(params)
    articles.value = res.data.data.records
    total.value = res.data.data.total
  } finally {
    loading.value = false
  }
}

function openPreview(id) {
  const base = import.meta.env.VITE_PORTAL_FRONT || ''
  window.open(`${base}/article/${id}`, '_blank')
}

async function doDelete(id) {
  await deleteArticle(id)
  fetchData()
}
</script>

<style scoped>
.article-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  padding: 20px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.page-title {
  font-size: 20px;
  color: #111827;
  font-weight: 700;
  margin: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #f8fafc;
}

.filter-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 700;
}

.filter-select { width: 108px; }

.table-container {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.article-title { color: #111827; font-weight: 600; }

.status-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; font-weight: 500;
  padding: 3px 9px; border-radius: 999px;
}
.status-badge.published { color: #047857; background: #ecfdf5; }
.status-badge.draft { color: #64748b; background: #f1f5f9; }

.visibility-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; font-weight: 500;
  padding: 3px 9px; border-radius: 999px;
}
.visibility-badge.public { color: #315987; background: #eff6ff; }
.visibility-badge.rag_only { color: #6d28d9; background: #f5f3ff; }
.visibility-badge.private { color: #64748b; background: #f1f5f9; }

.view-count { font-size: 13px; color: #909399; }
.time-cell { font-size: 12px; color: #909399; }

.actions { display: flex; gap: 6px; justify-content: center; flex-wrap: wrap; }
.action-btn {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 6px 9px; border-radius: 6px; border: 1px solid transparent;
  font-size: 11px; cursor: pointer;
  transition: all 0.2s; background: none;
}
.action-btn.preview { color: #047857; border-color: #d1fae5; }
.action-btn.preview:hover { background: #ecfdf5; border-color: #10b981; }
.action-btn.edit { color: #315987; border-color: #dbeafe; }
.action-btn.edit:hover { background: #eff6ff; border-color: #426fa6; }
.action-btn.delete { color: #dc2626; border-color: #fee2e2; }
.action-btn.delete:hover { background: #fef2f2; border-color: #ef4444; }

.pagination { margin-top: 20px; display: flex; justify-content: flex-end; }

@media (max-width: 820px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
