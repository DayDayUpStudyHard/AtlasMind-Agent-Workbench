<template>
  <div class="about-edit">
    <div class="page-header">
      <h3 class="page-title">关于页面</h3>
      <el-button type="primary" size="small" @click="save" :loading="saving">保存</el-button>
    </div>

    <div class="editor-card">
      <div class="editor-section">
        <h4 class="section-title">Markdown 内容</h4>
        <el-input v-model="content" type="textarea" :rows="16" placeholder="写点什么..." />
      </div>
      <div class="editor-section">
        <h4 class="section-title">个人时间线</h4>
        <div class="timeline-editor">
          <div v-for="(item, i) in timeline" :key="i" class="timeline-row">
            <el-input v-model="item.year" placeholder="年份" style="width:100px" size="small" />
            <el-input v-model="item.title" placeholder="标题" style="width:180px" size="small" />
            <el-input v-model="item.desc" placeholder="描述" style="flex:1" size="small" />
            <el-button size="small" type="danger" text @click="timeline.splice(i, 1)">删除</el-button>
          </div>
          <el-button size="small" @click="timeline.push({ year: '', title: '', desc: '' })">+ 添加时间节点</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAbout, updateAbout } from '../api/index.js'

const content = ref('')
const timeline = ref([])
const saving = ref(false)

onMounted(async () => {
  try {
    const res = await getAbout()
    const data = res.data.data
    content.value = data.content || ''
    try { timeline.value = JSON.parse(data.timeline || '[]') } catch { timeline.value = [] }
  } catch {}
})

async function save() {
  saving.value = true
  try {
    await updateAbout({ content: content.value, timeline: JSON.stringify(timeline.value) })
    ElMessage.success('保存成功')
  } finally { saving.value = false }
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }
.editor-card {
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px; padding: 24px 28px;
  max-width: 800px;
}
.editor-section { margin-bottom: 24px; }
.section-title { font-size: 14px; color: #303133; font-weight: 600; margin: 0 0 10px; }
.timeline-editor { display: flex; flex-direction: column; gap: 6px; }
.timeline-row { display: flex; gap: 6px; align-items: center; }
</style>
