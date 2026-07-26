<template>
  <div class="comments">
    <div class="section-head">
      <h3 class="section-title">留言 <span class="title-count">({{ total }})</span></h3>
      <div class="section-line"></div>
    </div>

    <div v-if="rootComments.length" class="comment-list">
      <div v-for="(c, i) in rootComments" :key="c.id" class="comment-item" :style="{ '--i': i }">
        <div class="comment-avatar">
          <span class="avatar-text">{{ c.author.charAt(0) }}</span>
        </div>
        <div class="comment-body">
          <div class="comment-head">
            <span class="author">{{ c.author }}</span>
            <span class="time">{{ formatDate(c.createTime) }}</span>
          </div>
          <p class="content">{{ c.content }}</p>
          <button class="reply-trigger" @click="startReply(c.id, c.author)">回复</button>
        </div>
      </div>

      <!-- 内联回复表单 -->
      <div v-if="replyingId" class="reply-form-wrap">
        <div class="reply-form-card">
          <div class="reply-to-label">回复 @{{ replyForm.replyTo }}</div>
          <div class="form-row">
            <n-input v-model:value="replyForm.author" placeholder="你的昵称" size="small" class="form-input" />
            <n-input v-model:value="replyForm.email" placeholder="邮箱（选填）" size="small" class="form-input" />
          </div>
          <n-input v-model:value="replyForm.content" type="textarea" :rows="3" placeholder="写下你的回复..." />
          <div class="reply-actions">
            <n-button size="small" @click="submitReply" :loading="submitting" type="primary">发送回复</n-button>
            <n-button size="small" @click="cancelReply">取消</n-button>
          </div>
        </div>
      </div>
    </div>
    <div v-else class="empty-state">暂无留言，来发表第一条吧</div>

    <!-- 主评论表单 -->
    <div class="comment-form">
      <div class="form-head">
        <h4>发表留言</h4>
        <span class="form-hint">畅所欲言</span>
      </div>
      <div class="form-card">
        <div class="form-row">
          <n-input v-model:value="form.author" placeholder="昵称" class="form-input" :input-props="{ autocomplete: 'off' }" />
          <n-input v-model:value="form.email" placeholder="邮箱（选填）" class="form-input" :input-props="{ autocomplete: 'off' }" />
        </div>
        <n-input v-model:value="form.content" type="textarea" :rows="3" placeholder="写下你的想法..." />
        <n-button @click="submit" :loading="submitting" class="submit-btn" :disabled="!form.author || !form.content">
          <template #icon>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </template>
          发送
        </n-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { addComment } from '../api/index.js'

const props = defineProps({ articleId: Number, comments: Array, total: Number })
const emit = defineEmits(['refresh'])

const form = ref({ author: '', email: '', content: '' })
const submitting = ref(false)
const replyingId = ref(null)
const replyForm = ref({ author: '', email: '', content: '', replyTo: '', parentId: null })

// Group comments: root (parentId == null) vs replies
const rootComments = computed(() => {
  return (props.comments || [])
    .filter(c => !c.parentId)
    .map(root => ({
      ...root,
      replies: (props.comments || [])
        .filter(r => r.parentId === root.id)
        .sort((a, b) => (a.createTime || '').localeCompare(b.createTime || ''))
    }))
})

function startReply(parentId, author) {
  replyingId.value = parentId
  replyForm.value = { author: '', email: '', content: '', replyTo: author, parentId }
}

function cancelReply() {
  replyingId.value = null
  replyForm.value = { author: '', email: '', content: '', replyTo: '', parentId: null }
}

async function submitReply() {
  if (!replyForm.value.author || !replyForm.value.content) return
  submitting.value = true
  try {
    const payload = {
      author: replyForm.value.author,
      email: replyForm.value.email,
      content: replyForm.value.content,
      parentId: replyForm.value.parentId,
      replyTo: replyForm.value.replyTo
    }
    await addComment(props.articleId, payload)
    cancelReply()
    emit('refresh')
  } finally { submitting.value = false }
}

async function submit() {
  if (!form.value.author || !form.value.content) return
  submitting.value = true
  try {
    await addComment(props.articleId, form.value)
    form.value = { author: '', email: '', content: '' }
    emit('refresh')
  } finally { submitting.value = false }
}

function formatDate(d) { return d ? d.substring(0, 16) : '' }
</script>

<style scoped>
.comments { margin-top: 56px; }

.section-head { margin-bottom: 20px; }
.section-title { font-size: 17px; color: #303133; margin-bottom: 10px; font-weight: 600; }
.title-count { color: #909399; font-size: 14px; font-weight: 400; }
.section-line { height: 1px; background: var(--atlas-border); }

/* ═══ Comment Items ═══ */
.comment-item {
  display: flex; gap: 14px; padding: 18px 0;
  border-bottom: 1px solid #f0f2f5;
  animation: commentEnter 0.3s ease forwards;
  animation-delay: calc(var(--i) * 0.05s);
  opacity: 0;
}
.comment-avatar {
  width: 40px; height: 40px; border-radius: 10px; flex-shrink: 0;
  background: var(--atlas-surface-soft);
  display: flex; align-items: center; justify-content: center;
}
.avatar-text { color: var(--atlas-primary); font-size: 16px; font-weight: 700; }
.comment-body { flex: 1; min-width: 0; }
.comment-head { display: flex; gap: 12px; align-items: center; margin-bottom: 6px; }
.author { font-weight: 600; color: var(--atlas-primary); font-size: 14px; }
.time { color: #c0c4cc; font-size: 12px; }
.content { color: #606266; font-size: 14px; line-height: 1.7; margin-bottom: 6px; }

/* Reply trigger */
.reply-trigger {
  background: none; border: none; color: #909399; font-size: 12px;
  cursor: pointer; padding: 2px 6px; border-radius: 4px; transition: all 0.15s;
}
.reply-trigger:hover { color: var(--atlas-primary); background: var(--atlas-surface-soft); }

/* ═══ Nested Replies ═══ */
.nested-replies {
  margin-top: 4px;
  padding-left: 52px;
  position: relative;
}
.nested-replies::before {
  content: '';
  position: absolute; left: 20px; top: 0; bottom: 0;
  width: 2px; background: var(--atlas-primary);
  border-radius: 1px;
  opacity: 0.4;
}
.reply-item {
  display: flex; gap: 12px; padding: 10px 0;
  border-bottom: none;
}
.reply-avatar-small {
  width: 32px; height: 32px; border-radius: 8px; flex-shrink: 0;
  background: var(--atlas-surface-soft);
  display: flex; align-items: center; justify-content: center;
}
.reply-avatar-small .avatar-text { font-size: 13px; }
.reply-body { flex: 1; min-width: 0; }
.reply-to-badge {
  display: inline-block; font-size: 11px; color: var(--atlas-primary);
  background: #ecf5ff; padding: 1px 6px; border-radius: 3px;
  margin-right: 6px;
}

/* ═══ Inline Reply Form ═══ */
.reply-form-wrap { margin-top: 8px; }
.reply-form-card {
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(64,158,255,0.15);
  border-radius: 10px; padding: 16px;
}
.reply-to-label { font-size: 13px; color: var(--atlas-primary); font-weight: 500; margin-bottom: 10px; }
.reply-actions { display: flex; gap: 8px; margin-top: 10px; }

.empty-state {
  color: #c0c4cc; font-size: 14px; padding: 32px 0; text-align: center;
}

/* ═══ Main Form ═══ */
.comment-form { margin-top: 40px; }
.form-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.form-head h4 { font-size: 15px; color: #303133; font-weight: 600; margin: 0; }
.form-hint { font-size: 12px; color: #c0c4cc; }
.form-card {
  background: rgba(255,255,255,0.6);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.5);
  border-radius: 12px; padding: 20px;
}
.form-row { display: flex; gap: 12px; margin-bottom: 14px; }
.form-input { flex: 1; }

.submit-btn {
  margin-top: 14px;
  --n-color: #ecf5ff !important;
  --n-color-hover: #d9ecff !important;
  --n-border: 1px solid var(--atlas-primary) !important;
  --n-border-hover: 1px solid #66b1ff !important;
  --n-text-color: var(--atlas-primary) !important;
  --n-text-color-hover: var(--atlas-primary) !important;
  font-size: 12px !important;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 2px 8px rgba(64,158,255,0.12);
}
.submit-btn:hover {
  box-shadow: 0 4px 14px rgba(64,158,255,0.2);
  transform: translateY(-1px);
}

@keyframes commentEnter {
  0% { opacity: 0; transform: translateX(-6px); }
  100% { opacity: 1; transform: translateX(0); }
}
</style>
