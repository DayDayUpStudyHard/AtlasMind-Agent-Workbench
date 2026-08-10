<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">Organization</span>
        <h2>部门管理</h2>
        <p>管理部门/公司组织架构</p>
      </div>
      <el-button type="primary" @click="openCreate">新建部门</el-button>
    </section>

    <el-table :data="list" stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="部门名称" min-width="150">
        <template #default="{ row }"><strong>{{ row.name }}</strong></template>
      </el-table-column>
      <el-table-column prop="code" label="编码" width="120">
        <template #default="{ row }">{{ row.code || '-' }}</template>
      </el-table-column>
      <el-table-column label="默认部门" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.isDefault === 1 ? 'success' : 'info'" effect="plain" size="small">
            {{ row.isDefault === 1 ? '是' : '否' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatDate(row.createTime) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="row.isDefault !== 1" size="small" type="danger" @click="doDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogOpen" :title="editingDept ? '编辑部门' : '新建部门'" width="460px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="部门名称">
          <el-input v-model="form.name" placeholder="请输入部门名称" />
        </el-form-item>
        <el-form-item label="部门编码">
          <el-input v-model="form.code" placeholder="请输入部门编码" :disabled="!!editingDept" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" placeholder="可选" />
        </el-form-item>
      </el-form>
      <p v-if="error" class="error-copy">{{ error }}</p>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="doSave">
          {{ saving ? '保存中...' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
  } catch { ElMessage.error('加载部门列表失败') } finally { loading.value = false }
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
      ElMessage.success('部门已更新')
    } else {
      await createAdminDepartment({ name: form.value.name, code: form.value.code, description: form.value.description })
      ElMessage.success('部门已创建')
    }
    dialogOpen.value = false
    fetchList()
  } catch (err) {
    error.value = err.response?.data?.message || '保存失败'
  } finally { saving.value = false }
}

async function doDelete(dept) {
  try {
    await ElMessageBox.confirm(`确定删除部门「${dept.name}」吗？`, '确认删除', { type: 'warning' })
  } catch { return }
  try {
    await deleteAdminDepartment(dept.id)
    ElMessage.success('部门已删除')
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '删除失败')
  }
}

function formatDate(v) { if (!v) return '-'; return String(v).replace('T', ' ').slice(0, 19) }
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }
.error-copy { color: #f56c6c; font-size: 12px; margin: 0 0 8px; }
</style>
