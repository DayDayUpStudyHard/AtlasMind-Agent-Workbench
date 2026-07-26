<template>
  <div class="home-ai-page">
    <section class="ai-stage" :class="{ 'is-chatting': messages.length > 0 }">
      <div v-if="messages.length === 0" class="ai-welcome">
        <span class="eyebrow">AtlasMind AI</span>
        <h1>先问，再读。</h1>
        <p>从你的文章、学习笔记和项目复盘里找到答案。</p>
      </div>

      <div v-else ref="messageList" class="conversation">
        <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
          <span class="message-label">{{ message.role === 'user' ? '你' : 'AtlasMind AI' }}</span>
          <div class="message-content" v-html="renderMarkdown(message.content)"></div>
          <div v-if="message.sources?.length" class="source-list">
            <span class="source-heading">参考来源</span>
            <router-link
              v-for="source in message.sources"
              :key="source.id"
              :to="`/article/${source.id}`"
              target="_blank"
              class="source-link"
            >
              {{ source.title }}
            </router-link>
          </div>
        </div>
        <div v-if="streaming" class="message assistant">
          <span class="message-label">AtlasMind AI</span>
          <span class="streaming-status">{{ streamingStatus || '正在整理答案' }}</span>
        </div>
      </div>

      <form class="ai-composer" @submit.prevent="submitQuestion">
        <textarea
          v-model="inputText"
          rows="1"
          :disabled="streaming"
          placeholder="问问你的知识库，例如：这个项目的 RAG 是怎么工作的？"
          @keydown.enter.exact.prevent="submitQuestion"
        ></textarea>
        <button type="submit" class="send-button" :disabled="streaming || !inputText.trim()" aria-label="发送问题" title="发送问题">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" />
          </svg>
        </button>
      </form>

      <div v-if="messages.length === 0" class="prompt-list">
        <button v-for="prompt in prompts" :key="prompt" type="button" class="prompt-chip" @click="usePrompt(prompt)">
          {{ prompt }}
        </button>
      </div>
    </section>

    <section class="content-section">
      <div class="section-heading">
        <div>
          <span class="section-kicker">Knowledge stream</span>
          <h2>{{ keyword ? '搜索结果' : '继续阅读' }}</h2>
          <p>回答之后，再展开你感兴趣的文章和说说。</p>
        </div>
        <router-link to="/archive" class="section-link">查看时间线</router-link>
      </div>

      <div v-if="keyword" class="search-state">
        <span>正在查看“{{ keyword }}”</span>
        <button type="button" @click="clearSearch">清除</button>
      </div>

      <div class="content-layout">
        <main class="article-stream">
          <n-spin :show="loading">
            <transition-group name="list" tag="div" class="article-list">
              <ArticleCard v-for="(article, index) in articles" :key="article.id" :article="article" :style="{ '--i': index }" />
            </transition-group>
          </n-spin>
          <div v-if="total > size" class="pagination">
            <n-pagination v-model:page="page" :page-size="size" :item-count="total" @update:page="fetchArticles" />
          </div>
          <n-empty v-if="!loading && articles.length === 0" description="暂无文章" class="empty-state" />
        </main>

        <aside class="content-aside">
          <router-link v-if="featuredArticle" :to="`/article/${featuredArticle.id}`" class="featured-entry">
            <span class="aside-kicker">Latest post</span>
            <strong>{{ featuredArticle.title }}</strong>
            <p>{{ featuredArticle.summary || '打开文章查看完整内容。' }}</p>
          </router-link>
          <div v-if="recentMoments.length" class="moments-entry">
            <router-link to="/moments" class="aside-heading">最新说说</router-link>
            <router-link v-for="moment in recentMoments" :key="moment.id" to="/moments" class="moment-row">
              <span>{{ moment.content }}</span>
              <time>{{ formatDate(moment.createTime) }}</time>
            </router-link>
          </div>
        </aside>
      </div>
    </section>

    <BackToTop />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { useRoute, useRouter } from 'vue-router'
import {
  appendAiMessage,
  createAiSession,
  getAiSessionMessages,
  getArticles,
  getMoments,
  getRuntimeConfig
} from '../api/index.js'
import ArticleCard from '../components/ArticleCard.vue'
import BackToTop from '../components/BackToTop.vue'

const route = useRoute()
const router = useRouter()
const articles = ref([])
const recentMoments = ref([])
const loading = ref(false)
const page = ref(1)
const size = 6
const total = ref(0)
const keyword = ref('')
const inputText = ref('')
const messages = ref([])
const streaming = ref(false)
const streamingStatus = ref('')
const messageList = ref(null)
const sessionId = ref(null)
const sessionToken = ref('')
const runtimeConfig = ref({ aiEnabled: true, aiTopK: 5, aiMaxTopK: 10 })

const prompts = [
  '帮我总结最近的项目复盘',
  '我该怎样准备 Agent 面试？',
  '解释一下这个知识工作台的技术架构',
]

const featuredArticle = computed(() => articles.value[0] || null)

onMounted(async () => {
  keyword.value = route.query.keyword || ''
  await restoreSession()
  await loadRuntimeConfig()
  fetchArticles()
  fetchMoments()
})

watch(() => route.query.keyword, (value) => {
  keyword.value = value || ''
  page.value = 1
  fetchArticles()
})

function formatDate(value) {
  return value ? value.substring(0, 10) : ''
}

function renderMarkdown(value) {
  return value ? marked.parse(value, { breaks: true }) : ''
}

function usePrompt(prompt) {
  inputText.value = prompt
  submitQuestion()
}

function clearSearch() {
  router.replace({ path: '/' })
  keyword.value = ''
  page.value = 1
  fetchArticles()
}

async function fetchArticles() {
  loading.value = true
  try {
    const params = { page: page.value, size }
    if (keyword.value) params.keyword = keyword.value
    const response = await getArticles(params)
    articles.value = response.data.data.records
    total.value = response.data.data.total
  } finally {
    loading.value = false
  }
}

async function fetchMoments() {
  try {
    const response = await getMoments({ page: 1, size: 3 })
    recentMoments.value = response.data.data.records
  } catch {}
}

async function submitQuestion() {
  const content = inputText.value.trim()
  if (!content || streaming.value) return

  const activeSessionId = await ensureSession()
  inputText.value = ''
  messages.value.push({ role: 'user', content })
  const assistantMessage = { role: 'assistant', content: '', sources: [] }
  messages.value.push(assistantMessage)
  streaming.value = true
  const startedAt = Date.now()
  streamingStatus.value = '正在检索相关内容'
  await scrollMessages()

  if (activeSessionId) {
    appendAiMessage(activeSessionId, { role: 'user', content }, sessionToken.value).catch(() => {})
  }

  try {
    const history = messages.value.slice(0, -1).map((message) => ({
      role: message.role,
      content: message.content,
    }))
    if (!runtimeConfig.value.aiEnabled) {
      throw new Error('AI 功能当前已关闭')
    }
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        history,
        topK: runtimeConfig.value.aiTopK
      }),
    })
    if (!response.ok || !response.body) throw new Error(`请求失败：${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let eventType = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
          continue
        }
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (eventType === 'status') {
            streamingStatus.value = data.status === 'thinking' ? '正在生成回答' : '正在检索相关内容'
          } else if (eventType === 'chunk') {
            streamingStatus.value = ''
            assistantMessage.content += data.content
            await scrollMessages()
          } else if (eventType === 'sources') {
            assistantMessage.sources = data.sources || []
          } else if (eventType === 'error') {
            assistantMessage.content += `\n\n*抱歉，出错了：${data.error || '未知错误'}*`
          }
        } catch {}
      }
    }
  } catch (error) {
    assistantMessage.content = `暂时无法完成回答。\n\n*${error.message || '请确认 AI 服务是否已启动'}*`
  } finally {
    if (activeSessionId && assistantMessage.content) {
      appendAiMessage(activeSessionId, {
        role: 'assistant',
        content: assistantMessage.content,
        latencyMs: Date.now() - startedAt
      }, sessionToken.value).catch(() => {})
    }
    streamingStatus.value = ''
    streaming.value = false
    await scrollMessages()
  }
}

async function restoreSession() {
  const storedId = Number(localStorage.getItem('atlasmind-ai-session') || 0)
  const storedToken = localStorage.getItem('atlasmind-ai-session-token') || ''
  if (!storedId || !storedToken) return
  try {
    const response = await getAiSessionMessages(storedId, storedToken)
    sessionId.value = storedId
    sessionToken.value = storedToken
    messages.value = (response.data.data || []).map((message) => ({
      role: message.role,
      content: message.content,
      sources: []
    }))
  } catch {
    localStorage.removeItem('atlasmind-ai-session')
    localStorage.removeItem('atlasmind-ai-session-token')
  }
}

async function ensureSession() {
  if (sessionId.value) return sessionId.value
  try {
    const response = await createAiSession({ source: 'FRONT', scope: 'GLOBAL' })
    sessionId.value = response.data.data?.id || null
    sessionToken.value = response.data.data?.ownerToken || ''
    if (sessionId.value) {
      localStorage.setItem('atlasmind-ai-session', String(sessionId.value))
      localStorage.setItem('atlasmind-ai-session-token', sessionToken.value)
    }
    return sessionId.value
  } catch {
    return null
  }
}

async function loadRuntimeConfig() {
  try {
    const response = await getRuntimeConfig()
    runtimeConfig.value = {
      ...runtimeConfig.value,
      ...(response.data.data || {})
    }
  } catch {}
}

async function scrollMessages() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}
</script>

<style scoped>
.home-ai-page { display: flex; flex-direction: column; gap: 52px; }
.ai-stage { min-height: 430px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 38px 0 24px; }
.ai-stage.is-chatting { align-items: stretch; justify-content: flex-start; min-height: 420px; padding-top: 28px; }
.ai-welcome { text-align: center; }
.eyebrow, .section-kicker, .aside-kicker { color: var(--atlas-primary); font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
.ai-welcome h1 { margin: 16px 0 10px; color: var(--atlas-text); font-size: clamp(40px, 6vw, 60px); line-height: 1; letter-spacing: 0; }
.ai-welcome p, .section-heading p { color: var(--atlas-muted); font-size: 16px; line-height: 1.7; }
.ai-composer { width: min(680px, 100%); display: flex; align-items: flex-end; gap: 8px; margin-top: 28px; padding: 7px; background: var(--atlas-surface); border: 1px solid var(--atlas-border); border-radius: 16px; box-shadow: var(--atlas-shadow); transition: border-color .18s, box-shadow .18s; }
.ai-stage.is-chatting .ai-composer { align-self: center; margin-top: 24px; }
.ai-composer:focus-within { border-color: var(--atlas-primary); box-shadow: 0 0 0 4px rgba(37,99,235,.1), var(--atlas-shadow); }
.ai-composer textarea { min-height: 42px; max-height: 140px; flex: 1; resize: vertical; padding: 10px 11px; color: var(--atlas-text); background: transparent; border: 0; outline: 0; line-height: 1.5; }
.ai-composer textarea::placeholder { color: var(--atlas-subtle); }
.send-button { width: 44px; height: 44px; flex: 0 0 auto; display: grid; place-items: center; color: #fff; background: var(--atlas-text); border: 0; border-radius: 12px; cursor: pointer; transition: background .18s, transform .18s; }
.send-button:hover:not(:disabled) { background: var(--atlas-primary); transform: translateY(-1px); }
.send-button:disabled { opacity: .4; cursor: not-allowed; }
.prompt-list { width: min(680px, 100%); display: flex; justify-content: center; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.prompt-chip { padding: 8px 12px; color: var(--atlas-muted); background: transparent; border: 1px solid var(--atlas-border); border-radius: 999px; cursor: pointer; font-size: 12px; transition: color .18s, border-color .18s, background .18s; }
.prompt-chip:hover { color: var(--atlas-primary); background: var(--atlas-surface); border-color: rgba(37,99,235,.35); }
.conversation { width: min(780px, 100%); max-height: 320px; overflow-y: auto; align-self: center; padding: 8px 4px; }
.message { max-width: 760px; margin-bottom: 24px; }
.message.user { margin-left: auto; padding: 14px 16px; color: #fff; background: var(--atlas-text); border-radius: 16px 16px 4px 16px; }
.message.assistant { padding-left: 18px; border-left: 2px solid var(--atlas-primary); }
.message-label { display: block; margin-bottom: 8px; color: var(--atlas-subtle); font-size: 12px; font-weight: 700; }
.message-content { line-height: 1.8; }
.message-content :deep(p) { margin: 0 0 10px; }
.message-content :deep(p:last-child) { margin-bottom: 0; }
.source-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--atlas-border); }
.source-heading { width: 100%; color: var(--atlas-subtle); font-size: 12px; }
.source-link { padding: 6px 9px; color: var(--atlas-muted); background: var(--atlas-surface-soft); border: 1px solid var(--atlas-border); border-radius: 999px; font-size: 12px; text-decoration: none; }
.source-link:hover { color: var(--atlas-primary); border-color: rgba(37,99,235,.3); }
.streaming-status { color: var(--atlas-muted); font-size: 13px; }
.content-section { padding-top: 32px; border-top: 1px solid var(--atlas-border); }
.section-heading { display: flex; justify-content: space-between; align-items: end; gap: 24px; margin-bottom: 24px; }
.section-heading h2 { margin: 6px 0; color: var(--atlas-text); font-size: 30px; line-height: 1.2; }
.section-link { color: var(--atlas-muted); font-size: 13px; text-decoration: none; }
.section-link:hover { color: var(--atlas-primary); }
.search-state { display: flex; align-items: center; gap: 10px; margin: -8px 0 18px; color: var(--atlas-muted); font-size: 13px; }
.search-state button { padding: 4px 9px; color: var(--atlas-primary); background: transparent; border: 1px solid var(--atlas-border); border-radius: 6px; cursor: pointer; font-size: 12px; }
.content-layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 28px; align-items: start; }
.article-list { display: flex; flex-direction: column; gap: 12px; }
.content-aside { display: flex; flex-direction: column; gap: 14px; }
.featured-entry, .moments-entry { display: block; padding: 18px; color: inherit; background: var(--atlas-surface); border: 1px solid var(--atlas-border); border-radius: 8px; text-decoration: none; }
.featured-entry strong { display: block; margin-top: 10px; color: var(--atlas-text); font-size: 18px; line-height: 1.45; }
.featured-entry p { margin-top: 8px; color: var(--atlas-muted); font-size: 13px; line-height: 1.65; }
.aside-heading { display: block; margin-bottom: 12px; color: var(--atlas-text); font-size: 14px; font-weight: 700; text-decoration: none; }
.moment-row { display: block; padding: 10px 0; color: var(--atlas-text); border-top: 1px solid var(--atlas-border); text-decoration: none; }
.moment-row:first-of-type { border-top: 0; padding-top: 0; }
.moment-row span { display: -webkit-box; overflow: hidden; color: var(--atlas-muted); font-size: 13px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.moment-row time { display: block; margin-top: 6px; color: var(--atlas-subtle); font-size: 12px; }
.pagination { display: flex; justify-content: center; margin-top: 28px; }
.empty-state { margin-top: 40px; }
.list-enter-active { transition: opacity .25s ease, transform .25s ease; }
.list-enter-from { opacity: 0; transform: translateY(10px); }
@media (max-width: 960px) { .content-layout { grid-template-columns: 1fr; } .content-aside { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .home-ai-page { gap: 40px; } .ai-stage { min-height: 400px; padding: 24px 0 18px; } .ai-welcome h1 { font-size: 42px; } .ai-welcome p { font-size: 14px; } .ai-composer { margin-top: 24px; } .section-heading { align-items: flex-start; flex-direction: column; gap: 10px; } .section-heading h2 { font-size: 26px; } .content-aside { grid-template-columns: 1fr; } }

/* Hallmark | Workbench surface: calm question field, blue ink, no AI gradients */
.ai-welcome h1,
.section-heading h2,
.featured-entry strong {
  font-family: var(--atlas-font-display);
}

.eyebrow,
.section-kicker,
.aside-kicker {
  color: var(--atlas-primary);
  letter-spacing: 0;
  text-transform: none;
}

.ai-composer {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
  border-radius: 4px;
  box-shadow: none;
}

.ai-composer:focus-within {
  border-color: var(--atlas-primary);
  box-shadow: 0 0 0 3px rgba(66, 111, 166, 0.12);
}

.send-button {
  background: var(--atlas-primary);
  border-radius: 3px;
}

.send-button:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
  transform: none;
}

.prompt-chip {
  color: var(--atlas-primary);
  border-color: var(--atlas-border);
  border-radius: 3px;
  background: transparent;
}

.prompt-chip:hover {
  color: var(--atlas-primary-dark);
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-primary);
}

.message.user {
  background: var(--atlas-primary);
  border-radius: 4px;
}

.message.assistant {
  border-left-color: var(--atlas-primary);
}

.source-link,
.featured-entry,
.moments-entry {
  border-radius: 4px;
}

.source-link {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-border);
}

.section-link {
  color: var(--atlas-primary);
}
</style>
