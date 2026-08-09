<template>
  <div class="users-page">
    <div class="page-head">
      <div>
        <h2>用户管理</h2>
        <p>管理平台用户账号、权限与配额</p>
      </div>
      <button class="primary-button" @click="openCreate">新建用户</button>
    </div>

    <div class="filter-bar">
      <input v-model="search" class="filter-input" placeholder="搜索用户名或昵称..." @keyup.enter="fetchList" />
      <select v-model="roleFilter" class="filter-select" @change="fetchList">
        <option value="">全部角色</option>
        <option value="ADMIN">管理员</option>
        <option value="USER">普通用户</option>
      </select>
      <select v-model="statusFilter" class="filter-select" @change="fetchList">
        <option value="">全部状态</option>
        <option value="ACTIVE">启用</option>
        <option value="DISABLED">禁用</option>
      </select>
      <button class="quiet-button" @click="fetchList">刷新</button>
    </div>

    <div v-if="loading" class="loading-state">加载中...</div>

    <table v-else class="data-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>用户名</th>
          <th>昵称</th>
          <th>角色</th>
          <th>部门</th>
          <th>状态</th>
          <th>创建时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in list" :key="user.id">
          <td>{{ user.id }}</td>
          <td><strong>{{ user.username }}</strong></td>
          <td>{{ user.nickname || '-' }}</td>
          <td><span class="role-tag" :class="user.role">{{ roleLabel(user.role) }}</span></td>
          <td>{{ user.departmentName || '-' }}</td>
          <td><span class="status-tag" :class="user.status">{{ statusLabel(user.status) }}</span></td>
          <td>{{ formatDate(user.createTime) }}</td>
          <td class="actions-cell">
            <button class="inline-btn" @click="openEdit(user)">编辑</button>
            <button class="inline-btn" @click="openQuotaAdjust(user)">额度</button>
            <button v-if="user.status === 'ACTIVE'" class="inline-btn danger" @click="doDisable(user)">禁用</button>
            <button v-else class="inline-btn" @click="doEnable(user)">启用</button>
          </td>
        </tr>
        <tr v-if="list.length === 0">
          <td colspan="8" class="empty-row">暂无用户数据</td>
        </tr>
      </tbody>
    </table>

    <!-- Create / Edit Dialog -->
    <div v-if="dialogOpen" class="dialog-overlay" @click.self="dialogOpen = false">
      <div class="dialog">
        <h3>{{ editingUser ? '编辑用户' : '新建用户' }}</h3>
        <label>用户名 <input v-model="form.username" :disabled="!!editingUser" /></label>
        <label v-if="!editingUser">密码 <input v-model="form.password" type="password" /></label>
        <label>昵称 <input v-model="form.nickname" /></label>
        <label>角色
          <select v-model="form.role">
            <option value="USER">普通用户</option>
            <option value="ADMIN">管理员</option>
          </select>
        </label>
        <label>部门
          <select v-model="form.departmentId">
            <option :value="null">无</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </label>
        <label v-if="!editingUser">初始额度 <input v-model.number="form.initialQuota" type="number" min="0" /></label>
        <p v-if="error" class="error-copy">{{ error }}</p>
        <div class="dialog-actions">
          <button class="quiet-button" @click="dialogOpen = false">取消</button>
          <button class="primary-button" :disabled="saving" @click="doSave">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- Quota Adjust Dialog -->
    <div v-if="quotaOpen" class="dialog-overlay" @click.self="quotaOpen = false">
      <div class="dialog">
        <h3>额度调整 — {{ quotaUser?.username }}</h3>
        <p>当前额度：{{ quotaUser?.quota?.usedCount || 0 }} / {{ quotaUser?.quota?.totalQuota || 0 }}</p>
        <label>调整量（正数增加，负数减少）<input v-model.number="quotaAmount" type="number" /></label>
        <label>备注 <input v-model="quotaNote" /></label>
        <p v-if="quotaError" class="error-copy">{{ quotaError }}</p>
        <div class="dialog-actions">
          <button class="quiet-button" @click="quotaOpen = false">取消</button>
          <button class="primary-button" :disabled="quotaSaving" @click="doAdjustQuota">{{ quotaSaving ? '调整中...' : '确认调整' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getAdminUsers, createAdminUser, updateAdminUser, disableAdminUser, enableAdminUser, adjustAdminUserQuota, getAdminDepartments } from '../api/index.js'

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
const quotaAmount = ref(0)
const quotaNote = ref('')
const quotaSaving = ref(false)
const quotaError = ref('')

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
  } catch {} finally { loading.value = false }
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
    } else {
      await createAdminUser({
        username: form.value.username,
        password: form.value.password,
        nickname: form.value.nickname,
        role: form.value.role,
        departmentId: form.value.departmentId,
        initialQuota: form.value.initialQuota
      })
    }
    dialogOpen.value = false
    fetchList()
  } catch (err) {
    error.value = err.response?.data?.message || '保存失败'
  } finally { saving.value = false }
}

async function doDisable(user) {
  if (!confirm(`确定禁用用户「${user.username}」吗？`)) return
  try { await disableAdminUser(user.id); fetchList() }
  catch (err) { alert(err.response?.data?.message || '操作失败') }
}

async function doEnable(user) {
  try { await enableAdminUser(user.id); fetchList() }
  catch (err) { alert(err.response?.data?.message || '操作失败') }
}

function openQuotaAdjust(user) {
  quotaUser.value = user
  quotaAmount.value = 0
  quotaNote.value = ''
  quotaError.value = ''
  quotaOpen.value = true
}

async function doAdjustQuota() {
  quotaError.value = ''
  quotaSaving.value = true
  try {
    await adjustAdminUserQuota(quotaUser.value.id, { delta: quotaAmount.value, remark: quotaNote.value })
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
.users-page { max-width: 1200px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
.page-head h2 { margin: 0; color: var(--atlas-text, #1f2d3d); font-size: 20px; }
.page-head p { margin: 4px 0 0; color: var(--atlas-muted, #8b9aaa); font-size: 12px; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 16px; align-items: center; }
.filter-input { min-height: 34px; padding: 0 10px; border: 1px solid #d4dde8; border-radius: 4px; font-size: 13px; width: 200px; }
.filter-select { min-height: 34px; padding: 0 8px; border: 1px solid #d4dde8; border-radius: 4px; font-size: 13px; background: #fff; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; padding: 10px 12px; background: #f3f6fa; color: #607184; font-weight: 800; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; border-bottom: 2px solid #dce4ee; }
.data-table td { padding: 10px 12px; border-bottom: 1px solid #eef1f5; color: #1f2d3d; }
.data-table tbody tr:hover { background: #f8fafc; }
.empty-row { text-align: center; color: #8b9aaa; padding: 40px !important; }

.role-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 800; }
.role-tag.ADMIN { background: #eef3f8; color: #426fa6; }
.role-tag.USER { background: #f3f6fa; color: #607184; }
.status-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 800; }
.status-tag.ACTIVE { background: #eaf5ea; color: #3f7f5d; }
.status-tag.DISABLED { background: #fef0ef; color: #b35c56; }

.actions-cell { display: flex; gap: 6px; }
.inline-btn { padding: 3px 10px; border: 1px solid #d4dde8; border-radius: 3px; background: #fff; color: #607184; font-size: 11px; font-weight: 700; cursor: pointer; }
.inline-btn:hover { color: #426fa6; border-color: #426fa6; }
.inline-btn.danger:hover { color: #b35c56; border-color: #b35c56; }

.dialog-overlay { position: fixed; inset: 0; z-index: 200; display: grid; place-items: center; background: rgba(22,35,48,.28); }
.dialog { width: min(480px, 90vw); max-height: 80vh; overflow-y: auto; padding: 24px; background: #fbfcfe; border: 1px solid #d4dde8; border-radius: 4px; box-shadow: 0 12px 28px rgba(31,45,61,.12); }
.dialog h3 { margin: 0 0 16px; color: #1f2d3d; font-size: 16px; }
.dialog label { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; color: #1f2d3d; font-size: 12px; font-weight: 800; }
.dialog input, .dialog select { min-height: 38px; padding: 0 10px; border: 1px solid #d4dde8; border-radius: 4px; font: inherit; font-weight: 400; }
.dialog input:focus, .dialog select:focus { border-color: #426fa6; outline: 0; box-shadow: 0 0 0 3px rgba(66,111,166,.12); }

.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }

.primary-button { min-height: 36px; padding: 0 18px; color: #fff; background: #426fa6; border: 1px solid #426fa6; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 800; }
.primary-button:hover:not(:disabled) { background: #315987; }
.primary-button:disabled { cursor: not-allowed; opacity: .6; }
.quiet-button { min-height: 36px; padding: 0 18px; color: #607184; background: #fff; border: 1px solid #d4dde8; border-radius: 4px; cursor: pointer; font-size: 13px; font-weight: 700; }
.quiet-button:hover { color: #426fa6; border-color: #426fa6; }

.error-copy { color: #b35c56; font-size: 12px; margin: 0 0 8px; }
.loading-state { padding: 60px 0; text-align: center; color: #8b9aaa; }
</style>
