<template>
  <div class="settings">
    <div class="page-header">
      <h3 class="page-title">系统设置</h3>
      <p class="page-subtitle">管理全局平台行为与 AI 运行参数</p>
    </div>

    <div class="settings-card">
      <el-tabs v-model="activeTab" class="settings-tabs">
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
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getRuntimeSettings, updateRuntimeSettings } from '../api/index.js'

const activeTab = ref('runtime')
const saving = ref(false)
const runtimeForm = ref({ topK: 5, maxTopK: 10, aiEnabled: true })

onMounted(async () => {
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
    ElMessage.success('系统设置已保存，新配置将在后续请求中生效')
  } finally { saving.value = false }
}
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0 0 4px; }
.page-subtitle { font-size: 13px; color: #8b9aaa; margin: 0; }

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

.field-hint { color: #94a3b8; font-size: 12px; margin-left: 10px; }
</style>
