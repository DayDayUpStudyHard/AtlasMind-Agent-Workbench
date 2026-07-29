<template>
  <div class="home-page">
    <section class="hero-shell">
      <div class="hero-copy">
        <div class="eyebrow">
          <span class="eyebrow-mark" aria-hidden="true"></span>
          AtlasMind Knowledge Agent
        </div>
        <h1>AtlasMind 知识首页</h1>
        <p>
          这里是项目知识、文章归档和 AI 问答的入口页。先看最新文档和状态，再进入知识库细看内容。
        </p>

        <div class="hero-actions">
          <button type="button" class="primary-action" @click="focusComposer">开始提问</button>
          <router-link to="/knowledge" class="secondary-action">浏览知识库</router-link>
        </div>

        <div class="hero-stats" aria-label="overview stats">
          <article v-for="stat in homeStats" :key="stat.label" class="stat-card">
            <span>{{ stat.label }}</span>
            <strong>{{ stat.value }}</strong>
          </article>
        </div>
      </div>

      <div class="hero-column">
        <section class="panel ask-panel">
          <div class="panel-head">
            <div>
              <span class="panel-kicker">AI 检索问答</span>
              <strong>轻量提问入口</strong>
            </div>
            <span class="panel-status" :class="{ muted: !runtimeConfig.aiEnabled }">
              {{ runtimeConfig.aiEnabled ? 'Enabled' : 'Disabled' }}
            </span>
          </div>

          <div v-if="messages.length" ref="messageList" class="conversation">
            <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
              <span class="message-label">{{ message.role === 'user' ? '你' : 'AtlasMind AI' }}</span>
              <div class="message-content" v-html="renderMarkdown(message.content)"></div>
              <div v-if="message.sources?.length" class="source-list">
                <span class="source-heading">参考来源</span>
                <component
                  v-for="source in message.sources"
                  :key="sourceKey(source)"
                  :is="source.sourceType === 'ARTICLE' ? 'router-link' : 'span'"
                  :to="source.sourceType === 'ARTICLE' ? `/article/${source.sourceId || source.id}` : undefined"
                  target="_blank"
                  class="source-link"
                >
                  <strong>#{{ source.rank || '-' }} {{ source.title }}</strong>
                  <small>{{ source.sourceType || 'ARTICLE' }} / score {{ formatScore(source.score) }}</small>
                  <span v-if="source.snippet" class="source-snippet">{{ source.snippet }}</span>
                </component>
              </div>
            </div>
            <div v-if="streaming" class="message assistant">
              <span class="message-label">AtlasMind AI</span>
              <span class="streaming-status">{{ streamingStatus || '正在整理回答' }}</span>
            </div>
          </div>

          <div v-else class="assistant-empty">
            <p>从一个具体问题开始，系统会返回答案、引用来源和检索轨迹。</p>
            <div class="prompt-list">
              <button v-for="prompt in prompts" :key="prompt" type="button" class="prompt-chip" @click="usePrompt(prompt)">
                {{ prompt }}
              </button>
            </div>
          </div>

          <form class="composer" @submit.prevent="submitQuestion">
            <textarea
              ref="questionInput"
              v-model="inputText"
              rows="1"
              :disabled="streaming"
              placeholder="问一个关于项目、文档或流程的问题"
              @keydown.enter.exact.prevent="submitQuestion"
            ></textarea>
            <button type="submit" class="send-button" :disabled="streaming || !inputText.trim()" aria-label="发送问题">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="m22 2-7 20-4-9-9-4Z" />
                <path d="M22 2 11 13" />
              </svg>
            </button>
          </form>
        </section>

        <section class="panel doc-panel">
          <div class="panel-head">
            <div>
              <span class="panel-kicker">Knowledge preview</span>
              <strong>最近上传的知识文档</strong>
            </div>
            <router-link to="/knowledge" class="panel-link">打开知识库</router-link>
          </div>

          <div v-if="visibleKnowledgeDocuments.length" class="doc-summary-list">
            <router-link
              v-for="doc in visibleKnowledgeDocuments"
              :key="doc.id"
              :to="`/knowledge?doc=${doc.id}`"
              class="doc-summary"
            >
              <span class="doc-space">{{ doc.spaceName || '未命名空间' }}</span>
              <strong>{{ doc.title }}</strong>
              <div class="doc-summary-meta">
                <span>{{ doc.fileName }} · {{ doc.fileType || 'FILE' }}</span>
                <span>Chunks {{ doc.chunkCount || 0 }}</span>
              </div>
            </router-link>
          </div>
          <div v-else class="loading-state">暂无可见知识文档</div>
        </section>
      </div>
    </section>

    <section class="section-band">
      <div class="section-head">
        <div>
          <span class="section-kicker">Knowledge preview</span>
          <h2>知识文档浏览</h2>
          <p>这里展示后台上传并完成解析的文档，点击可进入完整知识库浏览页。</p>
        </div>
        <router-link to="/knowledge" class="section-link">打开知识库</router-link>
      </div>

      <div v-if="kbLoading" class="loading-state">正在加载知识文档...</div>
      <div v-else class="doc-grid">
        <article v-for="doc in kbDocuments" :key="doc.id" class="doc-card">
          <div class="doc-card-head">
            <div>
              <span class="doc-space">{{ doc.spaceName || '未命名空间' }}</span>
              <strong>{{ doc.title }}</strong>
            </div>
            <span class="doc-status">{{ doc.status }}</span>
          </div>
          <p>{{ doc.fileName }} · {{ doc.fileType || 'FILE' }}</p>
          <div class="doc-meta">
            <span>Chunks {{ doc.chunkCount || 0 }}</span>
            <span>{{ formatDate(doc.createTime) }}</span>
          </div>
        </article>
        <div v-if="!kbDocuments.length" class="empty-state">暂无可见知识文档。</div>
      </div>
    </section>

    <section class="section-band">
      <div class="section-head">
        <div>
          <span class="section-kicker">Knowledge stream</span>
          <h2>继续阅读</h2>
          <p>回答之外，继续查看原文和项目记录。</p>
        </div>
        <router-link to="/archive" class="section-link">查看文章归档</router-link>
      </div>

      <div class="article-layout">
        <main class="article-stream">
          <n-spin :show="articleLoading">
            <transition-group name="list" tag="div" class="article-list">
              <ArticleCard v-for="(article, index) in articles" :key="article.id" :article="article" :style="{ '--i': index }" />
            </transition-group>
          </n-spin>
          <n-empty v-if="!articleLoading && articles.length === 0" description="暂无文章" class="empty-state" />
        </main>

        <aside class="aside-column">
          <router-link v-if="featuredArticle" :to="`/article/${featuredArticle.id}`" class="featured-entry">
            <span class="aside-kicker">Latest post</span>
            <strong>{{ featuredArticle.title }}</strong>
            <p>{{ featuredArticle.summary || '打开文章查看完整内容。' }}</p>
          </router-link>
          <div v-if="recentMoments.length" class="moments-entry">
            <router-link to="/moments" class="aside-heading">最新动态</router-link>
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
import { computed, nextTick, onMounted, ref } from 'vue'
import { marked } from 'marked'
import {
  createAiSession,
  getAiSessionMessages,
  getArticles,
  getKbDocuments,
  getMoments,
  getRuntimeConfig
} from '../api/index.js'
import ArticleCard from '../components/ArticleCard.vue'
import BackToTop from '../components/BackToTop.vue'

const articles = ref([])
const recentMoments = ref([])
const kbDocuments = ref([])
const articleLoading = ref(false)
const kbLoading = ref(false)
const page = ref(1)
const size = 6
const inputText = ref('')
const messages = ref([])
const streaming = ref(false)
const streamingStatus = ref('')
const messageList = ref(null)
const questionInput = ref(null)
const sessionId = ref(null)
const sessionToken = ref('')
const runtimeConfig = ref({ aiEnabled: true, aiTopK: 5, aiMaxTopK: 10 })

const prompts = [
  '这个项目的 RAG 是怎么工作的？',
  '帮我总结最近的项目复盘',
  '哪些文档适合了解 Agent 架构？'
]

const featuredArticle = computed(() => articles.value[0] || null)
const visibleKnowledgeDocuments = computed(() => kbDocuments.value.slice(0, 3))
const homeStats = computed(() => [
  { label: '知识文档', value: kbDocuments.value.length },
  { label: '文章归档', value: articles.value.length },
  { label: '最近动态', value: recentMoments.value.length },
  { label: 'AI 状态', value: runtimeConfig.value.aiEnabled ? '已开启' : '已关闭' }
])

onMounted(async () => {
  await restoreSession()
  await loadRuntimeConfig()
  loadArticles()
  loadMoments()
  loadKnowledge()
})

function formatDate(value) {
  return value ? String(value).slice(0, 10) : ''
}

function formatScore(value) {
  const score = Number(value || 0)
  return score ? score.toFixed(3) : '0'
}

function sourceKey(source) {
  return `${source.sourceType || 'ARTICLE'}-${source.sourceId || source.id || 'x'}-${source.chunkId || 'root'}-${source.rank || 0}`
}

function renderMarkdown(value) {
  return value ? marked.parse(value, { breaks: true }) : ''
}

function focusComposer() {
  questionInput.value?.focus()
}

function usePrompt(prompt) {
  inputText.value = prompt
  submitQuestion()
}

async function loadArticles() {
  articleLoading.value = true
  try {
    const response = await getArticles({ page: page.value, size })
    articles.value = response.data.data.records || []
  } finally {
    articleLoading.value = false
  }
}

async function loadMoments() {
  try {
    const response = await getMoments({ page: 1, size: 3 })
    recentMoments.value = response.data.data.records || []
  } catch {}
}

async function loadKnowledge() {
  kbLoading.value = true
  try {
    const response = await getKbDocuments({ page: 1, size: 6 })
    kbDocuments.value = response.data.data.records || []
  } catch {
    kbDocuments.value = []
  } finally {
    kbLoading.value = false
  }
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
  streamingStatus.value = '正在检索相关内容'
  await scrollMessages()

  try {
    const history = messages.value.slice(0, -1).map((message) => ({
      role: message.role,
      content: message.content
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
        topK: runtimeConfig.value.aiTopK,
        sessionId: activeSessionId,
        ownerToken: sessionToken.value
      })
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
/* Hallmark 路 macrostructure: Home Dashboard 路 tone: calm editorial 路 anchor hue: slate-blue */
.home-page {
  display: flex;
  flex-direction: column;
  gap: 34px;
  overflow-x: hidden;
}

.hero-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(340px, 0.92fr);
  gap: 26px;
  align-items: start;
  padding-top: 20px;
}

.hero-copy,
.hero-column {
  min-width: 0;
}

.hero-copy {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding-top: 10px;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: fit-content;
  color: var(--atlas-primary);
  font-size: 13px;
  font-weight: 700;
}

.eyebrow-mark {
  width: 10px;
  height: 10px;
  border: 2px solid var(--atlas-primary);
  border-radius: 2px;
}

.hero-copy h1 {
  max-width: 620px;
  margin: 16px 0 14px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: clamp(42px, 5.2vw, 64px);
  line-height: 1.06;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.hero-copy p {
  max-width: 640px;
  color: var(--atlas-muted);
  font-size: 16px;
  line-height: 1.85;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 26px;
}

.primary-action,
.secondary-action,
.panel-link,
.section-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 42px;
  padding: 0 16px;
  border-radius: 4px;
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
}

.primary-action {
  color: var(--atlas-surface);
  background: var(--atlas-primary);
  border: 1px solid var(--atlas-primary);
  cursor: pointer;
}

.primary-action:hover {
  background: var(--atlas-primary-dark);
  border-color: var(--atlas-primary-dark);
}

.secondary-action,
.section-link,
.panel-link {
  color: var(--atlas-primary);
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
}

.secondary-action:hover,
.section-link:hover,
.panel-link:hover {
  color: var(--atlas-primary-dark);
  border-color: var(--atlas-primary);
}

.hero-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 30px;
}

.stat-card {
  padding: 14px 14px 12px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.stat-card span {
  display: block;
  color: var(--atlas-subtle);
  font-size: 12px;
  font-weight: 700;
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 20px;
  line-height: 1.2;
}

.hero-column {
  display: grid;
  gap: 14px;
}

.panel {
  min-width: 0;
  padding: 16px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--atlas-border);
}

.panel-kicker,
.section-kicker,
.aside-kicker {
  display: block;
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
}

.panel-head strong {
  display: block;
  margin-top: 5px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 20px;
  line-height: 1.25;
}

.panel-status {
  flex: 0 0 auto;
  padding: 4px 8px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}

.panel-status.muted {
  color: var(--atlas-subtle);
}

.assistant-empty {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 0 10px;
}

.assistant-empty p {
  margin: 0;
  color: var(--atlas-muted);
  font-size: 14px;
  line-height: 1.7;
}

.prompt-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.prompt-chip {
  width: 100%;
  padding: 10px 12px;
  color: var(--atlas-text);
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
  text-align: left;
}

.prompt-chip:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.conversation {
  max-height: 270px;
  overflow-y: auto;
  padding: 14px 2px 10px 0;
}

.message {
  max-width: 100%;
  margin-bottom: 16px;
}

.message.user {
  margin-left: auto;
  padding: 12px 14px;
  color: var(--atlas-surface);
  background: var(--atlas-primary);
  border-radius: 4px;
}

.message.assistant {
  padding-left: 12px;
  border-left: 2px solid var(--atlas-primary);
}

.message-label {
  display: block;
  margin-bottom: 8px;
  color: var(--atlas-subtle);
  font-size: 12px;
  font-weight: 700;
}

.message.user .message-label {
  color: rgba(255, 255, 255, 0.82);
}

.message-content {
  line-height: 1.75;
}

.message-content :deep(p) {
  margin: 0 0 10px;
}

.message-content :deep(p:last-child) {
  margin-bottom: 0;
}

.source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--atlas-border);
}

.source-heading {
  width: 100%;
  color: var(--atlas-subtle);
  font-size: 12px;
}

.source-link {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 9px;
  color: var(--atlas-muted);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  font-size: 12px;
  text-decoration: none;
}

.source-link strong {
  color: var(--atlas-text);
  font-weight: 700;
}

.source-link small {
  color: var(--atlas-subtle);
}

.source-snippet {
  line-height: 1.5;
}

.source-link:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

.streaming-status {
  color: var(--atlas-muted);
  font-size: 13px;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--atlas-border);
}

.composer textarea {
  min-height: 44px;
  max-height: 128px;
  flex: 1;
  resize: vertical;
  padding: 11px 12px;
  color: var(--atlas-text);
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  outline: 0;
  line-height: 1.5;
}

.composer textarea:focus {
  border-color: var(--atlas-primary);
  box-shadow: 0 0 0 3px rgba(66, 111, 166, 0.12);
}

.composer textarea::placeholder {
  color: var(--atlas-subtle);
}

.send-button {
  width: 44px;
  height: 44px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  color: var(--atlas-surface);
  background: var(--atlas-primary);
  border: 0;
  border-radius: 4px;
  cursor: pointer;
}

.send-button:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

.send-button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.doc-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.doc-summary-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.doc-summary {
  display: block;
  padding: 12px 13px;
  color: inherit;
  text-decoration: none;
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
}

.doc-summary:hover {
  border-color: var(--atlas-primary);
}

.doc-summary strong {
  display: block;
  margin-top: 6px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 17px;
  line-height: 1.25;
}

.doc-summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 8px;
  color: var(--atlas-subtle);
  font-size: 12px;
}

.section-band {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-top: 4px;
}

.section-head {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: 24px;
}

.section-head h2 {
  margin: 6px 0;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 32px;
  line-height: 1.2;
}

.section-head p {
  color: var(--atlas-muted);
  font-size: 15px;
  line-height: 1.7;
}

.doc-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.doc-card {
  padding: 16px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
}

.doc-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.doc-card strong {
  display: block;
  margin-top: 6px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 18px;
  line-height: 1.3;
}

.doc-space {
  display: block;
  color: var(--atlas-primary);
  font-size: 12px;
  font-weight: 700;
}

.doc-status {
  flex: 0 0 auto;
  padding: 4px 8px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
}

.doc-card p {
  margin: 10px 0 12px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
}

.doc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  color: var(--atlas-subtle);
  font-size: 12px;
}

.article-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 20px;
  align-items: start;
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.aside-column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.featured-entry,
.moments-entry {
  display: block;
  padding: 18px;
  color: inherit;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 6px;
  text-decoration: none;
}

.featured-entry strong {
  display: block;
  margin-top: 10px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 20px;
  line-height: 1.35;
}

.featured-entry p {
  margin-top: 8px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.65;
}

.aside-heading {
  display: block;
  margin-bottom: 12px;
  color: var(--atlas-text);
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
}

.moment-row {
  display: block;
  padding: 10px 0;
  color: var(--atlas-text);
  border-top: 1px solid var(--atlas-border);
  text-decoration: none;
}

.moment-row:first-of-type {
  border-top: 0;
  padding-top: 0;
}

.moment-row span {
  display: -webkit-box;
  overflow: hidden;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.moment-row time {
  display: block;
  margin-top: 6px;
  color: var(--atlas-subtle);
  font-size: 12px;
}

.loading-state,
.empty-state {
  padding: 24px 0;
  color: var(--atlas-muted);
}

.list-enter-active {
  transition: opacity 0.25s, transform 0.25s;
}

.list-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

@media (max-width: 1040px) {
  .hero-shell {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .doc-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .article-layout {
    grid-template-columns: 1fr;
  }

  .aside-column {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .home-page {
    gap: 26px;
  }

  .hero-shell {
    gap: 20px;
    padding-top: 8px;
  }

  .hero-copy h1 {
    font-size: 32px;
  }

  .hero-copy p {
    font-size: 15px;
  }

  .hero-stats,
  .doc-grid,
  .aside-column {
    grid-template-columns: 1fr;
  }

  .assistant-empty {
    padding-top: 12px;
  }

  .panel,
  .doc-card,
  .featured-entry,
  .moments-entry {
    padding: 14px;
  }

  .section-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  .section-head h2 {
    font-size: 28px;
  }
}
</style>
