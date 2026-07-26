<template>
  <div class="category-manage">
    <div class="page-header">
      <h3 class="page-title">分类管理</h3>
      <el-button type="primary" @click="showForm(null)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建分类
      </el-button>
    </div>

    <div class="table-container">
      <el-table :data="categories" v-loading="loading" stripe class="data-table">
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="name" label="名称" width="200">
          <template #default="{ row }">
            <span class="cat-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="280">
          <template #default="{ row }">
            <span class="cat-desc">{{ row.description || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="sort" label="排序" width="80" align="center">
          <template #default="{ row }">
            <span class="sort-num">{{ row.sort }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <div class="actions">
              <button class="action-btn edit" @click="showForm(row)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
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

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑分类' : '新建分类'" width="460px">
      <el-form :model="form" label-width="50px" class="dialog-form">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="分类名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="分类描述" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getCategories, createCategory, updateCategory, deleteCategory } from '../api/index.js'

const categories = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const form = ref({ name: '', description: '', sort: 0 })

onMounted(() => fetchData())

async function fetchData() {
  loading.value = true
  try { categories.value = (await getCategories()).data.data } finally { loading.value = false }
}

function showForm(row) {
  if (row) {
    editing.value = row
    form.value = { name: row.name, description: row.description || '', sort: row.sort || 0 }
  } else {
    editing.value = null
    form.value = { name: '', description: '', sort: 0 }
  }
  dialogVisible.value = true
}

async function save() {
  if (editing.value) {
    await updateCategory(editing.value.id, form.value)
  } else {
    await createCategory(form.value)
  }
  dialogVisible.value = false
  fetchData()
}

async function doDelete(id) {
  await deleteCategory(id)
  fetchData()
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }

.table-container {
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 12px; overflow: hidden;
}

.cat-name { color: #303133; font-weight: 500; }
.cat-desc { color: #909399; }
.sort-num { color: #909399; }

.actions { display: flex; gap: 6px; justify-content: center; }
.action-btn {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 5px 10px; border-radius: 5px; border: 1px solid transparent;
  font-size: 11px; cursor: pointer;
  transition: all 0.2s; background: none;
}
.action-btn.edit { color: #426fa6; border-color: #d9ecff; }
.action-btn.edit:hover { background: #ecf5ff; border-color: #426fa6; transform: translateY(-1px); }
.action-btn.del { color: #f56c6c; border-color: #fde2e2; }
.action-btn.del:hover { background: #fef0f0; border-color: #f56c6c; transform: translateY(-1px); }

.dialog-form { padding-top: 8px; }
</style>
