<template>
  <div class="settings">
    <div class="page-header">
      <h3 class="page-title">个人设置</h3>
    </div>

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
        <el-tab-pane name="runtime">
          <template #label>
            <span class="tab-label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
              AI 配置
            </span>
          </template>
          <el-form :model="runtimeForm" label-width="110px" class="settings-form">
            <el-form-item label="默认 Top-K">
              <el-input-number v-model="runtimeForm.topK" :min="1" :max="runtimeForm.maxTopK" />
              <span class="field-hint">用户端 AI 默认召回数量</span>
            </el-form-item>
            <el-form-item label="最大 Top-K">
              <el-input-number v-model="runtimeForm.maxTopK" :min="1" :max="20" />
              <span class="field-hint">限制用户端和检索测试的最大召回数量</span>
            </el-form-item>
            <el-form-item label="启用 AI">
              <el-switch v-model="runtimeForm.aiEnabled" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveRuntimeSettings" :loading="saving">
                保存 AI 配置
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
          <el-form :model="passwordForm" label-width="60px" class="settings-form">
            <el-form-item label="旧密码">
              <el-input v-model="passwordForm.oldPassword" type="password" show-password placeholder="输入当前密码" />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="passwordForm.newPassword" type="password" show-password placeholder="输入新密码" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="updatePassword" :loading="saving">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                更新
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getRuntimeSettings,
  getUserInfo,
  updateProfile as updateProfileApi,
  updatePassword as updatePasswordApi,
  updateRuntimeSettings
} from '../api/index.js'

const activeTab = ref('profile')
const saving = ref(false)
const profile = ref({ nickname: '', email: '', avatar: '', bio: '' })
const passwordForm = ref({ oldPassword: '', newPassword: '' })
const socialLinks = ref([])
const runtimeForm = ref({ topK: 5, maxTopK: 10, aiEnabled: true })

onMounted(async () => {
  try {
    const res = await getUserInfo()
    const user = res.data.data
    profile.value = { nickname: user.nickname || '', email: user.email || '', avatar: user.avatar || '', bio: user.bio || '' }
    try { socialLinks.value = JSON.parse(user.socialLinks || '[]') } catch { socialLinks.value = [] }
  } catch {}
  await loadRuntimeSettings()
})

async function loadRuntimeSettings() {
  try {
    const res = await getRuntimeSettings()
    const settings = res.data.data || []
    const values = Object.fromEntries(settings.map(item => [item.settingKey, item.settingValue]))
    runtimeForm.value = {
      topK: Number(values['ai.retrieval.top-k']) || 5,
      maxTopK: Number(values['ai.retrieval.max-top-k']) || 10,
      aiEnabled: values['ai.enabled'] !== 'false'
    }
  } catch {}
}

async function saveRuntimeSettings() {
  if (runtimeForm.value.topK > runtimeForm.value.maxTopK) {
    ElMessage.warning('默认 Top-K 不能大于最大 Top-K')
    return
  }
  saving.value = true
  try {
    await updateRuntimeSettings({
      'ai.retrieval.top-k': runtimeForm.value.topK,
      'ai.retrieval.max-top-k': runtimeForm.value.maxTopK,
      'ai.enabled': runtimeForm.value.aiEnabled
    })
    ElMessage.success('AI 配置已保存')
  } finally { saving.value = false }
}

async function updateProfile() {
  saving.value = true
  try {
    const data = { ...profile.value, socialLinks: JSON.stringify(socialLinks.value) }
    await updateProfileApi(data)
    ElMessage.success('保存成功')
  } finally { saving.value = false }
}

async function updatePassword() {
  if (!passwordForm.value.oldPassword || !passwordForm.value.newPassword) return
  saving.value = true
  try {
    await updatePasswordApi(passwordForm.value)
    ElMessage.success('密码修改成功')
    passwordForm.value = { oldPassword: '', newPassword: '' }
  } finally { saving.value = false }
}
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }

.settings-card {
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px; padding: 8px 32px 32px;
  max-width: 560px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 12px rgba(0,0,0,0.04);
}

.settings-tabs :deep(.el-tabs__header) { margin-bottom: 8px; }
.tab-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: inherit;
}

.settings-form { margin-top: 8px; }
.settings-form :deep(.el-form-item__label) {
  font-size: 12px; color: #606266; font-weight: 500;
}
.settings-form :deep(.el-button--primary) {
  display: flex; align-items: center; gap: 6px;
}

.social-links-editor { display: flex; flex-direction: column; gap: 6px; width: 100%; }
.social-row { display: flex; gap: 6px; align-items: center; }
.field-hint { color: #94a3b8; font-size: 12px; margin-left: 10px; }
</style>
