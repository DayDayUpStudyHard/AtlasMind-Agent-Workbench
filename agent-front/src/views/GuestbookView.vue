<template>
  <div class="guestbook-page">
    <div class="page-head">
      <h2 class="page-title">留言板</h2>
      <p class="page-desc">欢迎留言，打个招呼或留下建议</p>
      <div class="page-line"></div>
    </div>

    <div class="message-form glass-card">
      <h4 class="form-title">写留言</h4>
      <div class="form-row">
        <n-input v-model:value="form.author" placeholder="昵称 *" class="form-input" />
        <n-input v-model:value="form.email" placeholder="邮箱（选填）" class="form-input" />
      </div>
      <n-input v-model:value="form.content" type="textarea" :rows="3" placeholder="说点什么..." />
      <n-button type="primary" @click="submit" :loading="submitting" class="submit-btn">提交留言</n-button>
    </div>

    <n-spin :show="loading">
      <div class="message-list">
        <div v-for="m in messages" :key="m.id" class="message-card">
          <div class="msg-header">
            <n-avatar :size="36" class="msg-avatar" :style="{ background: '#eaf0f7' }">
              <span style="font-weight:600;color:#426fa6">{{ m.author.charAt(0) }}</span>
            </n-avatar>
            <div class="msg-meta">
              <span class="msg-author">{{ m.author }}</span>
              <span class="msg-time">{{ formatDate(m.createTime) }}</span>
            </div>
          </div>
          <p class="msg-content">{{ m.content }}</p>
        </div>
      </div>
    </n-spin>

    <div class="pagination" v-if="total > size">
      <n-pagination v-model:page="page" :page-size="size" :item-count="total" @update:page="fetchData" />
    </div>

    <n-empty v-if="!loading && messages.length === 0" description="暂无留言，来抢沙发吧" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { getGuestbookMessages, addGuestbookMessage } from '../api/index.js'

const message = useMessage()
const messages = ref([])
const loading = ref(false)
const submitting = ref(false)
const page = ref(1)
const size = 20
const total = ref(0)
const form = ref({ author: '', email: '', content: '' })

onMounted(() => fetchData())

function formatDate(t) {
  if (!t) return ''
  return t.substring(0, 16).replace('T', ' ')
}

async function fetchData() {
  loading.value = true
  try {
    const res = await getGuestbookMessages({ page: page.value, size: size })
    messages.value = res.data.data.records
    total.value = res.data.data.total
  } catch (err) {
    console.error('Guestbook load failed:', err)
    message.error('加载留言失败，请检查网络或稍后重试')
  } finally { loading.value = false }
}

async function submit() {
  if (!form.value.author.trim() || !form.value.content.trim()) {
    message.warning('请填写昵称和内容')
    return
  }
  if (form.value.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.value.email.trim())) {
    message.warning('请输入正确的邮箱格式')
    return
  }
  submitting.value = true
  try {
    await addGuestbookMessage(form.value)
    form.value = { author: '', email: '', content: '' }
    message.success('留言成功')
    page.value = 1
    fetchData()
  } finally { submitting.value = false }
}
</script>

<style scoped>
.guestbook-page { padding: 28px 0; }
.page-head { margin-bottom: 28px; }
.page-title { font-size: 22px; color: #303133; margin-bottom: 6px; font-weight: 600; }
.page-desc { font-size: 14px; color: #909399; margin: 0 0 10px; }
.page-line { height: 1px; background: #e8ecf0; }

.message-form {
  padding: 22px 24px; margin-bottom: 32px; border-radius: 14px;
}
.form-title { font-size: 15px; color: #303133; font-weight: 600; margin: 0 0 14px; }
.form-row { display: flex; gap: 12px; margin-bottom: 12px; }
.form-input { flex: 1; }
.submit-btn { margin-top: 12px; }

.message-list { display: flex; flex-direction: column; gap: 14px; }
.message-card {
  background: rgba(255,255,255,0.55);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 14px; padding: 18px 22px;
  transition: all 0.2s;
}
.message-card:hover { border-color: #e0e4ea; box-shadow: 0 2px 12px rgba(0,0,0,0.04); }
.msg-header { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.msg-meta { display: flex; flex-direction: column; }
.msg-author { font-size: 14px; color: #303133; font-weight: 500; }
.msg-time { font-size: 12px; color: #c0c4cc; }
.msg-content { font-size: 14px; color: #606266; line-height: 1.65; margin: 0; }

.pagination { margin-top: 32px; display: flex; justify-content: center; }
</style>
