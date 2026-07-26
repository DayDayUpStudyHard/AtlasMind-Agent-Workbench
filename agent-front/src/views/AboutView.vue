<template>
  <div class="about-page">
    <div class="page-head">
      <h2 class="page-title">关于</h2>
      <p class="page-desc">关于 AtlasMind Agent Workbench</p>
      <div class="page-line"></div>
    </div>

    <n-spin :show="loading">
      <div class="markdown-body glass-card" v-html="renderedContent"></div>

      <div class="timeline-section" v-if="timeline.length > 0">
        <div class="section-head">
          <h3>个人时间线</h3>
          <div class="head-line"></div>
        </div>
        <div class="timeline">
          <div v-for="(item, i) in timeline" :key="i" class="tl-item">
            <div class="tl-dot"></div>
            <div class="tl-card">
              <span class="tl-year">{{ item.year }}</span>
              <h4 class="tl-title">{{ item.title }}</h4>
              <p class="tl-desc">{{ item.desc }}</p>
            </div>
          </div>
        </div>
      </div>
    </n-spin>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { marked } from 'marked'
import { getAbout } from '../api/index.js'

const loading = ref(true)
const content = ref('')
const timeline = ref([])
const renderedContent = ref('<p style="color:#909399">加载中...</p>')

onMounted(async () => {
  try {
    const res = await getAbout()
    const data = res.data.data
    content.value = data.content || ''
    try { timeline.value = JSON.parse(data.timeline || '[]') } catch { timeline.value = [] }
    try { renderedContent.value = marked(content.value) } catch { renderedContent.value = '<p>内容渲染失败</p>' }
  } catch (err) {
    console.error('About page load failed:', err)
    content.value = '# 关于我\n\n这里是企业知识资产管理与 Agent 问答工作台。\n\n请确保后端服务已启动。'
    try { renderedContent.value = marked(content.value) } catch { renderedContent.value = '<p>关于我</p><p>这里是企业知识资产管理与 Agent 问答工作台。</p>' }
    timeline.value = []
  } finally { loading.value = false }
})
</script>

<style scoped>
.about-page { padding: 28px 0; }

.page-head { margin-bottom: 28px; }
.page-title { font-size: 22px; color: #303133; margin-bottom: 6px; font-weight: 600; }
.page-desc { font-size: 14px; color: #909399; margin: 0 0 10px; }
.page-line { height: 1px; background: #e8ecf0; }

.markdown-body {
  padding: 28px 32px; border-radius: 14px; margin-bottom: 36px;
}
.markdown-body :deep(h1) { font-size: 24px; margin-bottom: 16px; }
.markdown-body :deep(h2) { font-size: 18px; margin-top: 24px; margin-bottom: 12px; }
.markdown-body :deep(h3) { font-size: 16px; }
.markdown-body :deep(p) { line-height: 1.8; color: #606266; }
.markdown-body :deep(ul) { padding-left: 20px; }
.markdown-body :deep(li) { line-height: 1.8; color: #606266; }
.markdown-body :deep(strong) { color: #303133; }

.section-head { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.section-head h3 { font-size: 16px; color: #303133; font-weight: 600; margin: 0; white-space: nowrap; }
.head-line { flex: 1; height: 1px; background: #e8ecf0; }

.timeline { position: relative; padding-left: 28px; }
.timeline::before {
  content: ''; position: absolute; left: 9px; top: 0; bottom: 0;
  width: 2px; background: #426fa6;
}
.tl-item { position: relative; margin-bottom: 24px; }
.tl-dot {
  position: absolute; left: -24px; top: 8px;
  width: 12px; height: 12px; border-radius: 50%;
  background: #426fa6; border: 2px solid #fff;
  box-shadow: 0 0 0 3px rgba(64,158,255,0.2);
}
.tl-card {
  background: rgba(255,255,255,0.55);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 12px; padding: 16px 20px;
}
.tl-year { font-size: 12px; color: #426fa6; font-weight: 600; }
.tl-title { font-size: 15px; color: #303133; font-weight: 600; margin: 4px 0; }
.tl-desc { font-size: 13px; color: #909399; margin: 0; line-height: 1.6; }
</style>
