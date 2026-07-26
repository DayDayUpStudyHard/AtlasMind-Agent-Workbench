<template>
  <div class="article-edit">
    <div class="page-header">
      <h3 class="page-title">{{ isEdit ? '编辑文章' : '新建文章' }}</h3>
      <span class="mode-badge">{{ isEdit ? '编辑模式' : '新建模式' }}</span>
    </div>

    <div class="form-card">
      <el-form :model="form" :rules="rules" ref="formRef" label-width="50px" class="edit-form">
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="文章标题" size="large" class="title-input" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="form.summary" type="textarea" :rows="2" placeholder="留空则自动截取正文前200字" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="分类">
              <el-select v-model="form.categoryId" placeholder="选择分类" clearable style="width:100%">
                <el-option v-for="cat in categories" :key="cat.id" :label="cat.name" :value="cat.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="标签">
              <el-select v-model="form.tagIds" multiple placeholder="选择标签" style="width:100%">
                <el-option v-for="tag in tags" :key="tag.id" :label="tag.name" :value="tag.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="封面">
              <el-input v-model="form.cover" placeholder="封面图片URL" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="置顶">
              <div class="top-switch">
                <el-switch v-model="form.isTop" :active-value="1" :inactive-value="0" />
                <span class="top-label">{{ form.isTop ? '已置顶' : '普通' }}</span>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="可见性">
          <el-radio-group v-model="form.visibility" size="small">
            <el-radio value="PUBLIC">公开（展示在网站 + AI问答）</el-radio>
            <el-radio value="RAG_ONLY">仅AI问答（不出现在网站）</el-radio>
            <el-radio value="PRIVATE">私有（仅自己可见）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="内容" prop="content">
          <MdEditor v-model="form.content" language="en-US" style="height:520px" class="md-editor" :onUploadImg="onUploadImg" />
        </el-form-item>
        <el-form-item>
          <div class="form-actions">
            <el-button type="primary" @click="saveDraft">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
              保存草稿
            </el-button>
            <el-button type="success" @click="publish">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
              发布
            </el-button>
            <el-button @click="$router.back()">取消</el-button>
          </div>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAdminArticleDetail, createArticle, updateArticle, getCategories, getTags, uploadFile } from '../api/index.js'
import { MdEditor } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'

const route = useRoute()
const router = useRouter()
const isEdit = ref(false)
const formRef = ref(null)
const categories = ref([])
const tags = ref([])

const form = ref({
  title: '', content: '', summary: '', categoryId: null,
  tagIds: [], cover: '', isTop: 0, status: 0, visibility: 'PUBLIC'
})

const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  content: [{ required: true, message: '请输入内容', trigger: 'blur' }]
}

onMounted(async () => {
  const [catRes, tagRes] = await Promise.all([getCategories(), getTags()])
  categories.value = catRes.data.data
  tags.value = tagRes.data.data

  if (route.params.id) {
    isEdit.value = true
    const res = await getAdminArticleDetail(route.params.id)
    const article = res.data.data
    if (article) {
      Object.assign(form.value, {
        title: article.title, content: article.content || '',
        summary: article.summary || '', categoryId: article.categoryId,
        tagIds: article.tags ? article.tags.map(t => t.id) : [],
        cover: article.cover || '', isTop: article.isTop || 0,
        status: article.status || 0,
        visibility: article.visibility || 'PUBLIC'
      })
    }
  }
})

async function save(goBack = false) {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const data = { ...form.value }
  if (!data.summary && data.content) {
    data.summary = data.content.replace(/[#*>`\n\r]/g, '').substring(0, 200)
  }
  if (isEdit.value) {
    await updateArticle(route.params.id, data)
  } else {
    await createArticle(data)
  }
  if (goBack) router.push('/articles')
}

async function saveDraft() { form.value.status = 0; await save() }
async function publish() { form.value.status = 1; await save(true) }

async function onUploadImg(files, callback) {
  const urls = []
  for (const file of files) {
    const res = await uploadFile(file)
    const raw = res.data.data.url
    urls.push(raw.startsWith('http') ? raw : (import.meta.env.VITE_API_BASE || '') + raw)
  }
  callback(urls)
}
</script>

<style scoped>
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }
.mode-badge {
  font-size: 11px; color: #10b981; padding: 2px 10px; border-radius: 12px;
  background: #eef7f2; font-weight: 500;
}

.form-card {
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px; padding: 28px 28px 20px;
  max-width: 1000px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 12px rgba(0,0,0,0.04);
}

.edit-form :deep(.el-form-item__label) {
  font-size: 12px; color: #606266; font-weight: 500;
}

.title-input :deep(.el-input__inner) {
  font-size: 18px !important; font-weight: 600 !important;
}

.top-switch { display: flex; align-items: center; gap: 10px; }
.top-label { font-size: 12px; color: #909399; }

.form-actions { display: flex; gap: 10px; padding-top: 8px; }
</style>
