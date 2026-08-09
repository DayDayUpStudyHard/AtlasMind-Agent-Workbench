<template>
  <div class="departments-page">
    <div class="page-head">
      <div>
        <h2>部门管理</h2>
        <p>管理部门/公司组织架构</p>
      </div>
      <button class="primary-button" @click="openCreate">新建部门</button>
    </div>

    <div v-if="loading" class="loading-state">加载中...</div>

    <table v-else class="data-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>部门名称</th>
          <th>编码</th>
          <th>默认部门</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="dept in list" :key="dept.id">
          <td>{{ dept.id }}</td>
          <td><strong>{{ dept.name }}</strong></td>
          <td>{{ dept.code || '-' }}</td>
          <td>
            <span v-if="dept.isDefault === 1" class="badge yes">是</span>
            <span v-else class="badge no">否</span>
          </td>
          <td>{{ formatDate(dept.createTime) }}</td>
          <td class="actions-cell">
            <button class="inline-btn" @click="openEdit(dept)">编辑</button>
            <button v-if="dept.isDefault !== 1" class="inline-btn danger" @click="doDelete(dept)">删除</button>
          </td>
        </tr>
        <tr v-if="list.length === 0">
          <td colspan="6" class="empty-row">暂无部门数据</td>
        </tr>
      </tbody>
    </table>

    <!-- Create / Edit Dialog -->
    <div v-if="dialogOpen" class="dialog-overlay" @click.self="dialogOpen = false">
      <div class="dialog">
        <h3>{{ editingDept ? '编辑部门' : '新建部门' }}</h3>
        <label>部门名称 <input v-model="form.name" placeholder="请输入部门名称" /></label>
        <label>部门编码 <input v-model="form.code" placeholder="请输入部门编码" :disabled="!!editingDept" /></label>
        <label>描述 <input v-model="form.description" placeholder="可选" /></label>
        <p v-if="error" class="error-copy">{{ error }}</p>
        <div class="dialog-actions">
          <button class="quiet-button" @click="dialogOpen = false">取消</button>
          <button class="primary-button" :disabled="saving" @click="doSave">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getAdminDepartments, createAdminDepartment, updateAdminDepartment, deleteAdminDepartment } from '../api/index.js'

const loading = ref(false)
const list = ref([])

const dialogOpen = ref(false)
const editingDept = ref(null)
const saving = ref(false)
const error = ref('')
const form = ref({ name: '', code: '', description: '' })

onMounted(() => { fetchList() })

async function fetchList() {
  loading.value = true
  try {
    const res = await getAdminDepartments()
    list.value = res.data.data || []
  } catch {} finally { loading.value = false }
}

function openCreate() {
  editingDept.value = null
  form.value = { name: '', code: '', description: '' }
  error.value = ''
  dialogOpen.value = true
}

function openEdit(dept) {
  editingDept.value = dept
  form.value = { name: dept.name, code: dept.code || '', description: dept.description || '' }
  error.value = ''
  dialogOpen.value = true
}

async function doSave() {
  error.value = ''
  if (!form.value.name.trim()) { error.value = '请输入部门名称'; return }
  if (!editingDept.value && !form.value.code.trim()) { error.value = '请输入部门编码'; return }
  saving.value = true
  try {
    if (editingDept.value) {
      await updateAdminDepartment(editingDept.value.id, { name: form.value.name, description: form.value.description })
    } else {
      await createAdminDepartment({ name: form.value.name, code: form.value.code, description: form.value.description })
    }
    dialogOpen.value = false
    fetchList()
  } catch (err) {
    error.value = err.response?.data?.message || '保存失败'
  } finally { saving.value = false }
}

async function doDelete(dept) {
  if (!confirm(`确定删除部门「${dept.name}」吗？`)) return
  try {
    await deleteAdminDepartment(dept.id)
    fetchList()
  } catch (err) {
    alert(err.response?.data?.message || '删除失败')
  }
}

function formatDate(v) { if (!v) return '-'; return String(v).replace('T', ' ').slice(0, 19) }
</script>

<style scoped>
.departments-page { max-width: 900px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { margin: 0; color: var(--atlas-text, #1f2d3d); font-size: 20px; }
.page-head p { margin: 4px 0 0; color: var(--atlas-muted, #8b9aaa); font-size: 12px; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; padding: 10px 12px; background: #f3f6fa; color: #607184; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; border-bottom: 2px solid #dce4ee; }
.data-table td { padding: 10px 12px; border-bottom: 1px solid #eef1f5; color: #1f2d3d; }
.data-table tbody tr:hover { background: #f8fafc; }
.empty-row { text-align: center; color: #8b9aaa; padding: 40px !important; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 800; }
.badge.yes { background: #eaf5ea; color: #3f7f5d; }
.badge.no { background: #f3f6fa; color: #8b9aaa; }

.actions-cell { display: flex; gap: 6px; }
.inline-btn { padding: 3px 10px; border: 1px solid #d4dde8; border-radius: 3px; background: #fff; color: #607184; font-size: 11px; font-weight: 700; cursor: pointer; }
.inline-btn:hover { color: #426fa6; border-color: #426fa6; }
.inline-btn.danger:hover { color: #b35c56; border-color: #b35c56; }

.dialog-overlay { position: fixed; inset: 0; z-index: 200; display: grid; place-items: center; background: rgba(22,35,48,.28); }
.dialog { width: min(420px, 90vw); padding: 24px; background: #fbfcfe; border: 1px solid #d4dde8; border-radius: 4px; box-shadow: 0 12px 28px rgba(31,45,61,.12); }
.dialog h3 { margin: 0 0 16px; color: #1f2d3d; font-size: 16px; }
.dialog label { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; color: #1f2d3d; font-size: 12px; font-weight: 800; }
.dialog input { min-height: 38px; padding: 0 10px; border: 1px solid #d4dde8; border-radius: 4px; font: inherit; font-weight: 400; }
.dialog input:focus { border-color: #426fa6; outline: 0; box-shadow: 0 0 0 3px rgba(66,111,166,.12); }

.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }

.primary-button { min-height: 36px; padding: 0 18px; color: #fff; background: #426fa6; border: 1px solid #426fa6; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 800; }
.primary-button:hover:not(:disabled) { background: #315987; }
.primary-button:disabled { cursor: not-allowed; opacity: .6; }
.quiet-button { min-height: 36px; padding: 0 18px; color: #607184; background: #fff; border: 1px solid #d4dde8; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 700; }
.quiet-button:hover { color: #426fa6; border-color: #426fa6; }

.error-copy { color: #b35c56; font-size: 12px; margin: 0 0 8px; }
.loading-state { padding: 60px 0; text-align: center; color: #8b9aaa; }
</style>
