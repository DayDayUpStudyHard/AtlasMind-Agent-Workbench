<template>
  <div class="moment-manage">
    <div class="page-header">
      <h3 class="page-title">说说管理</h3>
      <el-button type="primary" size="small" @click="showForm(null)">新建说说</el-button>
    </div>

    <div class="table-container">
      <el-table :data="moments" v-loading="loading" stripe class="data-table">
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="content" label="内容" min-width="300" show-overflow-tooltip />
        <el-table-column prop="image" label="配图" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row.image" class="has-img">有</span>
            <span v-else class="no-img">无</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="time-cell">{{ row.createTime ? row.createTime.substring(0, 16) : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <div class="actions">
              <button class="action-btn edit" @click="showForm(row)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <el-popconfirm title="确定删除？" @confirm="doDelete(row.id)">
                <template #reference>
                  <button class="action-btn del" @click.stop>删除</button>
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

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑说说' : '新建说说'" width="500px" destroy-on-close>
      <el-form :model="form" label-width="50px">
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="4" placeholder="想说什么..." />
        </el-form-item>
        <el-form-item label="配图">
          <el-input v-model="form.image" placeholder="图片 URL（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getAdminMoments, createMoment, updateMoment, deleteMoment } from '../api/index.js'

const moments = ref([])
const loading = ref(false)
const page = ref(1)
const pageSize = 10
const total = ref(0)
const dialogVisible = ref(false)
const editing = ref(null)
const form = ref({ content: '', image: '' })

onMounted(() => fetchData())

async function fetchData() {
  loading.value = true
  try {
    const res = await getAdminMoments({ page: page.value, size: pageSize })
    moments.value = res.data.data.records
    total.value = res.data.data.total
  } finally { loading.value = false }
}

function showForm(row) {
  editing.value = row
  form.value = row ? { content: row.content, image: row.image || '' } : { content: '', image: '' }
  dialogVisible.value = true
}

async function save() {
  if (editing.value) {
    await updateMoment(editing.value.id, form.value)
  } else {
    await createMoment(form.value)
  }
  dialogVisible.value = false
  fetchData()
}

async function doDelete(id) {
  await deleteMoment(id)
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
.time-cell { font-size: 12px; color: #909399; }
.has-img { color: #67c23a; font-size: 12px; }
.no-img { color: #c0c4cc; font-size: 12px; }
.actions { display: flex; gap: 5px; justify-content: center; }
.action-btn {
  display: inline-flex; align-items: center; gap: 3px;
  padding: 4px 8px; border-radius: 5px; border: 1px solid transparent;
  font-size: 11px; cursor: pointer;
  transition: all 0.2s; background: none;
}
.action-btn.edit { color: #426fa6; border-color: #d9ecff; }
.action-btn.edit:hover { background: #ecf5ff; border-color: #426fa6; transform: translateY(-1px); }
.action-btn.del { color: #f56c6c; border-color: #fde2e2; }
.action-btn.del:hover { background: #fef0f0; border-color: #f56c6c; transform: translateY(-1px); }
.pagination { margin-top: 20px; display: flex; justify-content: flex-end; }
</style>
