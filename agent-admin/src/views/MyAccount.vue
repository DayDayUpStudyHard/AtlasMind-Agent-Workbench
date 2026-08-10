<template>
  <div class="my-account">
    <div class="page-header">
      <h3 class="page-title">我的账号</h3>
      <p class="page-subtitle">管理你的个人资料、密码与账号安全</p>
    </div>

    <div class="account-grid">
      <!-- 账号概览卡片 -->
      <div class="overview-card">
        <div class="overview-avatar">
          <span>{{ avatarLetter }}</span>
        </div>
        <div class="overview-body">
          <strong class="overview-name">{{ displayName }}</strong>
          <span class="overview-username">@{{ username }}</span>
          <div class="overview-tags">
            <span class="tag role-tag">{{ roleLabel }}</span>
            <span v-if="departmentName" class="tag dept-tag">{{ departmentName }}</span>
          </div>
        </div>
      </div>

      <!-- 个人资料 & 修改密码 -->
      <div class="settings-card">
        <el-tabs v-model="activeTab" class="settings-tabs">
          <el-tab-pane name="profile">
            <template #label>
              <span class="tab-label">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                个人资料
              </span>
            </template>
            <el-form :model="profile" label-width="60px" class="settings-form">
              <el-form-item label="昵称">
                <el-input v-model="profile.nickname" placeholder="你的昵称" />
              </el-form-item>
              <el-form-item label="邮箱">
                <el-input v-model="profile.email" placeholder="email@example.com" />
              </el-form-item>
              <el-form-item label="头像">
                <el-input v-model="profile.avatar" placeholder="https://..." />
              </el-form-item>
              <el-form-item label="简介">
                <el-input v-model="profile.bio" placeholder="一句话介绍自己" />
              </el-form-item>
              <el-form-item label="社交链接">
                <div class="social-links-editor">
                  <div v-for="(link, i) in socialLinks" :key="i" class="social-row">
                    <el-input v-model="link.name" placeholder="名称" style="width:100px" size="small" />
                    <el-input v-model="link.url" placeholder="URL" style="flex:1" size="small" />
                    <el-button size="small" type="danger" text @click="socialLinks.splice(i, 1)">删除</el-button>
                  </div>
                  <el-button size="small" @click="socialLinks.push({ name: '', url: '', icon: '' })">+ 添加</el-button>
                </div>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="updateProfile" :loading="saving">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                  保存
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane name="password">
            <template #label>
              <span class="tab-label">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                修改密码
              </span>
            </template>
            <el-form :model="passwordForm" label-width="80px" class="settings-form">
              <el-form-item label="当前密码">
                <el-input v-model="passwordForm.oldPassword" type="password" show-password placeholder="输入当前密码" />
              </el-form-item>
              <el-form-item label="新密码">
                <el-input v-model="passwordForm.newPassword" type="password" show-password placeholder="输入新密码" />
              </el-form-item>
              <el-form-item label="确认新密码">
                <el-input v-model="passwordForm.confirmPassword" type="password" show-password placeholder="再次输入新密码" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="updatePassword" :loading="saving">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                  更新密码
                </el-button>
              </el-form-item>
            </el-form>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user.js'
import { getUserInfo, updateProfile as updateProfileApi, updatePassword as updatePasswordApi } from '../api/index.js'

const router = useRouter()
const userStore = useUserStore()

const activeTab = ref('profile')
const saving = ref(false)
const profile = ref({ nickname: '', email: '', avatar: '', bio: '' })
const passwordForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const socialLinks = ref([])

const displayName = computed(() => userStore.displayName || '')
const username = computed(() => userStore.user?.username || '')
const avatarLetter = computed(() => userStore.avatarLetter || 'U')
const roleLabel = computed(() => userStore.roleLabel || '')
const departmentName = computed(() => userStore.departmentName || '')

onMounted(async () => {
  try {
    const res = await getUserInfo()
    const user = res.data.data
    profile.value = { nickname: user.nickname || '', email: user.email || '', avatar: user.avatar || '', bio: user.bio || '' }
    try { socialLinks.value = JSON.parse(user.socialLinks || '[]') } catch { socialLinks.value = [] }
  } catch {}
})

async function updateProfile() {
  saving.value = true
  try {
    const data = { ...profile.value, socialLinks: JSON.stringify(socialLinks.value) }
    await updateProfileApi(data)
    ElMessage.success('个人资料已更新')
  } finally { saving.value = false }
}

async function updatePassword() {
  if (!passwordForm.value.oldPassword || !passwordForm.value.newPassword) {
    ElMessage.warning('请填写当前密码和新密码')
    return
  }
  if (passwordForm.value.newPassword !== passwordForm.value.confirmPassword) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  saving.value = true
  try {
    await updatePasswordApi({ oldPassword: passwordForm.value.oldPassword, newPassword: passwordForm.value.newPassword })
    ElMessage.success('密码修改成功，请使用新密码重新登录')
    passwordForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
    // 修改密码后重新登录
    setTimeout(async () => {
      await userStore.logout()
      router.push('/login')
    }, 1200)
  } finally { saving.value = false }
}
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0 0 4px; }
.page-subtitle { font-size: 13px; color: #8b9aaa; margin: 0; }

.account-grid {
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 600px;
}

.overview-card {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 22px 28px;
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 12px rgba(0,0,0,0.04);
}

.overview-avatar {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 8px;
  background: #426fa6;
  color: #ffffff;
  font-size: 22px;
  font-weight: 800;
  flex-shrink: 0;
}

.overview-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.overview-name {
  color: #1f2d3d;
  font-size: 16px;
  font-weight: 800;
}

.overview-username {
  color: #8b9aaa;
  font-size: 13px;
}

.overview-tags {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 700;
}

.role-tag {
  color: #426fa6;
  background: rgba(66,111,166,0.12);
}

.dept-tag {
  color: #607184;
  background: rgba(96,113,132,0.1);
}

.settings-card {
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px;
  padding: 8px 32px 32px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 12px rgba(0,0,0,0.04);
}

.settings-tabs :deep(.el-tabs__header) { margin-bottom: 8px; }

.tab-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: inherit;
}

.settings-form { margin-top: 8px; }

.settings-form :deep(.el-form-item__label) {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
}

.settings-form :deep(.el-button--primary) {
  display: flex;
  align-items: center;
  gap: 6px;
}

.social-links-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.social-row {
  display: flex;
  gap: 6px;
  align-items: center;
}
</style>
