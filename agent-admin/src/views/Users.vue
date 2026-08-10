<template>
  <div class="page">
    <section class="page-head">
      <div>
        <span class="eyebrow">User Management</span>
        <h2>用户管理</h2>
        <p>管理平台用户账号、权限与配额</p>
      </div>
      <el-button type="primary" @click="openCreate">新建用户</el-button>
    </section>

    <section class="toolbar">
      <el-input v-model="search" clearable placeholder="搜索用户名或昵称..." style="width: 240px" @clear="fetchList" @keyup.enter="fetchList" />
      <el-select v-model="roleFilter" clearable placeholder="全部角色" style="width: 120px" @change="fetchList">
        <el-option label="管理员" value="ADMIN" />
        <el-option label="普通用户" value="USER" />
      </el-select>
      <el-select v-model="statusFilter" clearable placeholder="全部状态" style="width: 100px" @change="fetchList">
        <el-option label="启用" value="ACTIVE" />
        <el-option label="禁用" value="DISABLED" />
      </el-select>
      <el-button @click="fetchList">刷新</el-button>
    </section>

    <el-table :data="list" stripe v-loading="loading">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="username" label="用户名" width="120">
        <template #default="{ row }"><strong>{{ row.username }}</strong></template>
      </el-table-column>
      <el-table-column prop="nickname" label="昵称" width="120">
        <template #default="{ row }">{{ row.nickname || '-' }}</template>
      </el-table-column>
      <el-table-column label="角色" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.role === 'ADMIN' ? 'primary' : 'info'" effect="plain" size="small">
            {{ roleLabel(row.role) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="部门" min-width="120">
        <template #default="{ row }">{{ row.departmentName || '-' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="70" align="center">
        <template #default="{ row }">
          <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'danger'" effect="plain" size="small">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatDate(row.createTime) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="openQuotaAdjust(row)">额度</el-button>
          <el-button v-if="row.status === 'ACTIVE'" size="small" type="danger" @click="doDisable(row)">禁用</el-button>
          <el-button v-else size="small" type="success" @click="doEnable(row)">启用</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Create / Edit Dialog -->
    <el-dialog v-model="dialogOpen" :title="editingUser ? '编辑用户' : '新建用户'" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="!!editingUser" />
        </el-form-item>
        <el-form-item v-if="!editingUser" label="密码">
          <el-input v-model="form.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.nickname" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="普通用户" value="USER" />
            <el-option label="管理员" value="ADMIN" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="form.departmentId" clearable placeholder="无" style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!editingUser" label="初始额度">
          <el-input-number v-model="form.initialQuota" :min="0" style="width: 100%" />
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

    <!-- Quota Adjust Dialog -->
    <el-dialog v-model="quotaOpen" title="额度调整" width="460px">
      <p class="quota-info">用户：{{ quotaUser?.username }} &nbsp;|&nbsp; 当前额度：{{ quotaUser?.quota?.usedCount || 0 }} / {{ quotaUser?.quota?.totalQuota || 0 }}</p>
      <el-form :model="quotaForm" label-width="80px">
        <el-form-item label="调整量">
          <el-input-number v-model="quotaForm.amount" style="width: 100%" />
          <div class="form-tip">正数增加，负数减少</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="quotaForm.note" />
        </el-form-item>
      </el-form>
      <p v-if="quotaError" class="error-copy">{{ quotaError }}</p>
      <template #footer>
        <el-button @click="quotaOpen = false">取消</el-button>
        <el-button type="primary" :loading="quotaSaving" @click="doAdjustQuota">
          {{ quotaSaving ? '调整中...' : '确认调整' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getAdminUsers, createAdminUser, updateAdminUser, disableAdminUser, enableAdminUser,
  adjustAdminUserQuota, getAdminDepartments
} from '../api/index.js'

const loading = ref(false)
const list = ref([])
const departments = ref([])
const search = ref('')
const roleFilter = ref('')
const statusFilter = ref('')

const dialogOpen = ref(false)
const editingUser = ref(null)
const saving = ref(false)
const error = ref('')
const form = ref({ username: '', password: '', nickname: '', role: 'USER', departmentId: null, initialQuota: 100 })

const quotaOpen = ref(false)
const quotaUser = ref(null)
const quotaSaving = ref(false)
const quotaError = ref('')
const quotaForm = ref({ amount: 0, note: '' })

onMounted(() => { fetchList(); fetchDepartments() })

async function fetchList() {
  loading.value = true
  try {
    const params = {}
    if (search.value) params.keyword = search.value
    if (roleFilter.value) params.role = roleFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const res = await getAdminUsers(params)
    list.value = res.data.data?.records || res.data.data || []
  } catch { ElMessage.error('加载用户列表失败') } finally { loading.value = false }
}

async function fetchDepartments() {
  try {
    const res = await getAdminDepartments()
    departments.value = res.data.data || []
  } catch {}
}

function openCreate() {
  editingUser.value = null
  form.value = { username: '', password: '', nickname: '', role: 'USER', departmentId: null, initialQuota: 100 }
  error.value = ''
  dialogOpen.value = true
}

function openEdit(user) {
  editingUser.value = user
  form.value = { username: user.username, password: '', nickname: user.nickname || '', role: user.role, departmentId: user.departmentId }
  error.value = ''
  dialogOpen.value = true
}

async function doSave() {
  error.value = ''
  if (!form.value.username) { error.value = '请输入用户名'; return }
  if (!editingUser.value && !form.value.password) { error.value = '请输入密码'; return }
  saving.value = true
  try {
    if (editingUser.value) {
      await updateAdminUser(editingUser.value.id, {
        nickname: form.value.nickname,
        role: form.value.role,
        departmentId: form.value.departmentId
      })
      ElMessage.success('用户已更新')
    } else {
      await createAdminUser({
        username: form.value.username,
        password: form.value.password,
        nickname: form.value.nickname,
        role: form.value.role,
        departmentId: form.value.departmentId,
        initialQuota: form.value.initialQuota
      })
      ElMessage.success('用户已创建')
    }
    dialogOpen.value = false
    fetchList()
  } catch (err) {
    error.value = err.response?.data?.message || '保存失败'
  } finally { saving.value = false }
}

async function doDisable(user) {
  try {
    await ElMessageBox.confirm(`确定禁用用户「${user.username}」吗？`, '确认禁用', { type: 'warning' })
  } catch { return }
  try {
    await disableAdminUser(user.id)
    ElMessage.success('用户已禁用')
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '操作失败')
  }
}

async function doEnable(user) {
  try {
    await enableAdminUser(user.id)
    ElMessage.success('用户已启用')
    fetchList()
  } catch (err) {
    ElMessage.error(err.response?.data?.message || '操作失败')
  }
}

function openQuotaAdjust(user) {
  quotaUser.value = user
  quotaForm.value = { amount: 0, note: '' }
  quotaError.value = ''
  quotaOpen.value = true
}

async function doAdjustQuota() {
  quotaError.value = ''
  quotaSaving.value = true
  try {
    await adjustAdminUserQuota(quotaUser.value.id, { delta: quotaForm.value.amount, remark: quotaForm.value.note })
    ElMessage.success('额度已调整')
    quotaOpen.value = false
    fetchList()
  } catch (err) {
    quotaError.value = err.response?.data?.message || '调整失败'
  } finally { quotaSaving.value = false }
}

function roleLabel(r) { return { ADMIN: '管理员', USER: '普通用户' }[r] || r || '-' }
function statusLabel(s) { return { ACTIVE: '启用', DISABLED: '禁用' }[s] || s || '-' }
function formatDate(v) { if (!v) return '-'; return String(v).replace('T', ' ').slice(0, 19) }
</script>

<style scoped>
.page { display: flex; flex-direction: column; gap: 18px; }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.eyebrow { color: #426fa6; font-size: 12px; font-weight: 800; letter-spacing: .04em; text-transform: uppercase; }
.page-head h2 { margin: 6px 0 8px; color: #1f2d3d; font-size: 24px; }
.page-head p { max-width: 820px; margin: 0; color: #607184; line-height: 1.7; }
.toolbar { display: flex; align-items: center; gap: 12px; padding: 14px; background: #fff; border: 1px solid #dce4ee; border-radius: 4px; }
.error-copy { color: #f56c6c; font-size: 12px; margin: 8px 0 0; }
.quota-info { margin: 0 0 16px; color: #607184; font-size: 13px; }
.form-tip { color: #909399; font-size: 11px; margin-top: 4px; }
</style>
