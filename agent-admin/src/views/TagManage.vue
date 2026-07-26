<template>
  <div class="tag-manage">
    <div class="page-header">
      <h3 class="page-title">标签管理</h3>
      <el-button type="primary" @click="showForm(null)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建标签
      </el-button>
    </div>

    <div v-loading="loading" class="tag-grid">
      <div v-for="tag in tags" :key="tag.id" class="tag-card" @click="showForm(tag)">
        <span class="tag-name"># {{ tag.name }}</span>
        <span class="tag-id">ID:{{ tag.id }}</span>
        <el-popconfirm title="确定删除？" @confirm="doDelete(tag.id)">
          <template #reference>
            <button class="tag-close-btn" @click.stop>&times;</button>
          </template>
        </el-popconfirm>
      </div>
      <el-empty v-if="!loading && tags.length === 0" description="暂无标签" />
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑标签' : '新建标签'" width="400px">
      <el-input v-model="tagName" placeholder="标签名称" @keyup.enter="save" size="large" class="tag-input" />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getTags, createTag, updateTag, deleteTag } from '../api/index.js'

const tags = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const tagName = ref('')

onMounted(() => fetchData())

async function fetchData() {
  loading.value = true
  try { tags.value = (await getTags()).data.data } finally { loading.value = false }
}

function showForm(row) {
  if (row) {
    editing.value = row
    tagName.value = row.name
  } else {
    editing.value = null
    tagName.value = ''
  }
  dialogVisible.value = true
}

async function save() {
  if (!tagName.value.trim()) return
  if (editing.value) {
    await updateTag(editing.value.id, { name: tagName.value.trim() })
  } else {
    await createTag({ name: tagName.value.trim() })
  }
  dialogVisible.value = false
  fetchData()
}

async function doDelete(id) {
  await deleteTag(id)
  fetchData()
}
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.page-title { font-size: 18px; color: #303133; font-weight: 600; margin: 0; }

.tag-grid { display: flex; gap: 10px; flex-wrap: wrap; }

.tag-card {
  display: flex; align-items: center; gap: 10px;
  cursor: pointer; padding: 8px 16px; border-radius: 8px;
  background: rgba(255,255,255,0.7);
  border: 1px solid rgba(255,255,255,0.5);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.tag-card:hover {
  border-color: #426fa6;
  background: #f0f7ff;
  box-shadow: 0 4px 16px rgba(64,158,255,0.1);
  transform: translateY(-2px);
}

.tag-name { font-size: 13px; color: #426fa6; font-weight: 500; }
.tag-id { font-size: 11px; color: #c0c4cc; }
.tag-close-btn {
  background: none; border: none; color: #c0c4cc; font-size: 16px; cursor: pointer;
  padding: 0 2px; line-height: 1; transition: all 0.2s; border-radius: 3px;
}
.tag-close-btn:hover { color: #f56c6c; background: #fef0f0; }

.tag-input { padding-top: 8px; }
</style>
