<template>
  <div class="chat-widget" :class="{ 'contract-scope': hasContractScope }">
    <button
      class="chat-trigger"
      :class="{ active: panelOpen }"
      type="button"
      title="打开 AI 助手"
      aria-label="打开 AI 助手"
      @click="togglePanel"
    >
      <svg class="trigger-icon" width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <path d="M4 5h16v12H7l-3 3z" />
        <path d="M8 9h8M8 13h5" />
      </svg>
      <span class="trigger-label">AI 助手</span>
    </button>

    <Teleport to="body">
      <transition name="slide">
        <aside v-if="panelOpen" class="chat-panel" aria-label="AI 助手">
          <header class="chat-header">
            <div class="header-left">
              <span class="header-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path d="M4 4h12v12H4z" />
                  <path d="M8 8h12v12H8z" />
                </svg>
              </span>
              <div class="header-copy">
                <strong>{{ hasContractScope ? '合同助手' : '工作台助手' }}</strong>
                <small>{{ contextTitle }}</small>
              </div>
              <span class="header-badge">{{ hasContractScope ? 'CONTRACT' : 'GLOBAL' }}</span>
            </div>
            <button class="close-btn" type="button" aria-label="关闭" @click="panelOpen = false">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </header>

          <section class="chat-scope-bar">
            <div v-if="isContractRoute && project" class="locked-scope">
              <span>当前合同</span>
              <strong>{{ project.name }}</strong>
              <small>回答会优先使用本合同结构化事实、原文条款、可用知识库和 Agent 历史。</small>
            </div>
            <label v-else class="scope-picker">
              <span class="scope-label">对话范围</span>
              <select v-model="selectedProjectId" :disabled="streaming || projectsLoading" @change="handleProjectChange">
                <option value="">全局工作台（不跨全部合同全文检索）</option>
                <option v-for="item in projects" :key="item.id" :value="String(item.id)">
                  {{ item.name }}
                </option>
              </select>
              <small>{{ hasContractScope ? '已绑定所选合同。' : '首页默认只回答工作台与知识库问题，不自动遍历所有合同全文。' }}</small>
            </label>
          </section>

          <div ref="msgList" class="chat-messages">
            <div v-if="messages.length === 0" class="chat-empty">
              <p class="empty-kicker">{{ hasContractScope ? 'CONTRACT CHAT' : 'WORKBENCH CHAT' }}</p>
              <h3>{{ hasContractScope ? '问当前合同里的事实、条款、风险和履约证据。' : '问工作台、知识库和项目经验。' }}</h3>
              <p>
                {{ hasContractScope
                  ? '我会基于当前合同回答，并尽量附上原文条款、时间节点或知识库引用；未确认或证据不足会直接说明。'
                  : '首页不会默认跨全部合同全文检索。进入合同详情页后，我会自动绑定当前合同再回答。' }}
              </p>
              <div class="suggestions">
                <button v-for="s in activeSuggestions" :key="s" class="sug-chip" type="button" @click="send(s)">
                  {{ s }}
                </button>
              </div>
            </div>

            <div v-for="(msg, i) in messages" :key="i" class="msg-wrapper" :class="msg.role">
              <div class="msg-bubble">
                <div class="msg-content" v-html="renderMd(msg.content)"></div>
                <div v-if="msg.sources && msg.sources.length" class="msg-sources">
                  <div class="sources-label">参考依据</div>
                  <div v-for="s in msg.sources" :key="sourceKey(s)" class="source-item" tabindex="0">
                    <div class="source-topline">
                      <span class="source-rank">#{{ s.rank || '-' }}</span>
                      <strong>{{ s.title || '未命名来源' }}</strong>
                    </div>
                    <span class="source-meta">
                      {{ sourceTypeLabel(s.sourceType) }}
                      <template v-if="s.page"> · 第 {{ s.page }} 页</template>
                      <template v-if="Number(s.score || 0)"> · 相关度 {{ formatScore(s.score) }}</template>
                    </span>
                    <span class="source-snippet" :title="s.snippet">{{ s.snippet }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="streaming" class="msg-wrapper assistant">
              <div class="msg-bubble streaming">
                <span v-if="streamingStatus" class="streaming-text">{{ streamingStatus }}</span>
                <span v-else class="dot-pulse"></span>
              </div>
            </div>
          </div>

          <footer class="chat-input">
            <div v-if="hasContractScope" class="input-context" title="本次对话会绑定当前合同">
              <span class="context-dot"></span>
              <span>{{ contextTitle }}</span>
            </div>
            <input
              v-model="inputText"
              class="chat-input-field"
              :placeholder="hasContractScope ? '问当前合同的付款、验收、风险、履约证据...' : '输入问题，基于工作台与知识库回答...'"
              :disabled="streaming"
              @keydown.enter="send()"
            />
            <button class="chat-send-btn" type="button" :disabled="streaming || !inputText.trim()" @click="send()">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </footer>
        </aside>
      </transition>
    </Teleport>

    <div v-if="panelOpen" class="chat-overlay" @click="panelOpen = false"></div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { createAiSession, getAiSessionMessages, listContracts } from '../api/index.js'

const panelOpen = ref(false)
const route = useRoute()
const projects = ref([])
const projectsLoading = ref(false)
const selectedProjectId = ref('')
const project = ref(null)
const inputText = ref('')
const messages = ref([])
const streaming = ref(false)
const streamingStatus = ref('')
const msgList = ref(null)
const sessionId = ref(null)
const sessionToken = ref('')

const routeCaseId = computed(() => {
  const value = route.path.match(/^\/contracts\/(\d+)(?:\/|$)/)?.[1]
  const id = Number(value || 0)
  return Number.isFinite(id) && id > 0 ? id : null
})
const isContractRoute = computed(() => !!routeCaseId.value)
const hasContractScope = computed(() => !!project.value?.id)
const chatScope = computed(() => hasContractScope.value ? 'CONTRACT_CASE' : 'GLOBAL')
const contextTitle = computed(() => project.value?.name || '全局工作台')
const sessionStorageKey = computed(() => `atlasmind-chat-session-${chatScope.value}-${project.value?.id || 'global'}`)

const globalSuggestions = ref([
  '这个工作台目前能做什么？',
  '知识库里有哪些可用内容？',
  '我应该如何完善合同作业系统？',
])
const contractSuggestions = [
  '这份合同的关键付款条件是什么？',
  '当前合同有哪些主要风险？',
  '有哪些履约时间节点需要跟踪？',
  '如果我要证明某个节点已履约，需要哪些材料？',
]
const activeSuggestions = computed(() => hasContractScope.value ? contractSuggestions : globalSuggestions.value)

onMounted(async () => {
  await loadProjects()
  await applyRouteCase()
  await restoreSession()
  window.addEventListener('atlasmind:open-chat', handleOpenChat)
})

onBeforeUnmount(() => {
  window.removeEventListener('atlasmind:open-chat', handleOpenChat)
})

watch(routeCaseId, async () => {
  await applyRouteCase()
})

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value && messages.value.length === 0 && !hasContractScope.value) {
    loadSuggestions()
  }
}

async function handleOpenChat(event) {
  const detail = event?.detail || null
  const nextId = detail?.caseId || detail?.projectId || routeCaseId.value
  if (nextId) {
    await applyProject(findProject(nextId) || { id: nextId, name: detail?.caseTitle || detail?.projectName || `合同 #${nextId}` })
  }
  panelOpen.value = true
  if (!messages.value.length && !hasContractScope.value) loadSuggestions()
}

async function loadProjects() {
  projectsLoading.value = true
  try {
    const response = await listContracts()
    const cases = response.data.data || []
    projects.value = cases.map(item => ({
      id: item.id,
      name: item.title || item.caseKey || `合同 #${item.id}`,
    }))
  } catch {
    projects.value = []
  } finally {
    projectsLoading.value = false
  }
}

async function applyRouteCase() {
  if (!routeCaseId.value) {
    if (isContractRoute.value || project.value) {
      await applyProject(null)
    }
    return
  }
  const routeProject = findProject(routeCaseId.value) || { id: routeCaseId.value, name: `合同 #${routeCaseId.value}` }
  await applyProject(routeProject)
}

function findProject(projectId) {
  if (!projectId) return null
  return projects.value.find(item => String(item.id) === String(projectId)) || null
}

async function handleProjectChange() {
  await applyProject(selectedProjectId.value ? findProject(selectedProjectId.value) : null)
}

async function applyProject(nextProject) {
  const normalized = nextProject ? { id: nextProject.id, name: nextProject.name || `合同 #${nextProject.id}` } : null
  if (String(project.value?.id || '') === String(normalized?.id || '')) return
  project.value = normalized
  selectedProjectId.value = normalized ? String(normalized.id) : ''
  sessionId.value = null
  sessionToken.value = ''
  messages.value = []
  inputText.value = ''
  await restoreSession()
}

async function loadSuggestions() {
  try {
    const res = await fetch('/api/chat/suggestions')
    if (res.ok) {
      const data = await res.json()
      if (Array.isArray(data.suggestions) && data.suggestions.length) {
        globalSuggestions.value = data.suggestions
      }
    }
  } catch {}
}

async function restoreSession() {
  const storedId = Number(localStorage.getItem(sessionStorageKey.value) || 0)
  const storedToken = localStorage.getItem(sessionStorageKey.value + '-token') || ''
  if (!storedId || !storedToken) return
  try {
    const response = await getAiSessionMessages(storedId, storedToken)
    sessionId.value = storedId
    sessionToken.value = storedToken
    messages.value = (response.data.data || []).map(message => ({
      role: message.role,
      content: message.content,
      sources: [],
    }))
  } catch {
    localStorage.removeItem(sessionStorageKey.value)
    localStorage.removeItem(sessionStorageKey.value + '-token')
  }
}

async function ensureSession() {
  if (sessionId.value) return sessionId.value
  try {
    const activeCaseId = project.value?.id || null
    const response = await createAiSession({
      source: hasContractScope.value ? 'CONTRACT_CASE_ASSISTANT' : 'GLOBAL_ASSISTANT',
      scope: chatScope.value,
      caseId: activeCaseId,
      projectId: activeCaseId,
    })
    sessionId.value = response.data.data?.id || null
    sessionToken.value = response.data.data?.ownerToken || ''
    if (sessionId.value) {
      localStorage.setItem(sessionStorageKey.value, String(sessionId.value))
      localStorage.setItem(sessionStorageKey.value + '-token', sessionToken.value)
    }
    return sessionId.value
  } catch {
    return null
  }
}

function renderMd(text) {
  return text ? marked.parse(text, { breaks: true }) : ''
}

function formatScore(value) {
  const score = Number(value || 0)
  return score ? score.toFixed(3) : '0'
}

function sourceTypeLabel(type) {
  const map = {
    ARTICLE: '文章',
    DOCUMENT: '知识库文档',
    KB_CHUNK: '知识库文档',
    KB_DOCUMENT: '知识库文档',
    CONTRACT_CASE: '合同基本信息',
    CONTRACT_CLAUSE: '合同原文',
    CONTRACT_PROFILE: '合同画像',
    CONTRACT_TIMELINE: '履约节点',
    CONTRACT_STANDARD_CLAUSE: '标准条款',
    CONTRACT_HISTORY: '历史记录',
  }
  return map[type] || type || '知识来源'
}

function sourceKey(source) {
  return `${source.sourceType || 'SOURCE'}-${source.sourceId || source.id || 'x'}-${source.chunkId || 'root'}-${source.rank || 0}`
}

function scrollBottom() {
  nextTick(() => {
    if (msgList.value) msgList.value.scrollTop = msgList.value.scrollHeight
  })
}

async function send(msg) {
  const content = typeof msg === 'string' ? msg : inputText.value.trim()
  if (!content || streaming.value) return
  const activeSessionId = await ensureSession()
  if (typeof msg !== 'string') inputText.value = ''

  messages.value.push({ role: 'user', content, sources: null })
  scrollBottom()

  const assistantMsg = { role: 'assistant', content: '', sources: [] }
  messages.value.push(assistantMsg)
  streaming.value = true
  streamingStatus.value = hasContractScope.value ? '正在检索当前合同...' : '正在检索知识库...'

  try {
    const activeCaseId = project.value?.id || null
    const history = messages.value.slice(0, -1).map(item => ({ role: item.role, content: item.content }))
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        history,
        sessionId: activeSessionId,
        ownerToken: sessionToken.value,
        scope: chatScope.value,
        caseId: activeCaseId,
        projectId: activeCaseId,
      }),
    })
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`)
    }

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
            streamingStatus.value = data.status === 'thinking'
              ? '正在组织回答...'
              : (data.status === 'searching' ? (hasContractScope.value ? '正在检索当前合同...' : '正在检索知识库...') : data.status)
          } else if (eventType === 'chunk') {
            streamingStatus.value = ''
            assistantMsg.content += data.content
            scrollBottom()
          } else if (eventType === 'sources') {
            assistantMsg.sources = data.sources || []
            assistantMsg.traceId = data.traceId
          } else if (eventType === 'error') {
            assistantMsg.content += `\n\n*抱歉，处理失败：${data.error || '未知错误'}*`
          }
        } catch {}
      }
    }
  } catch {
    assistantMsg.content += '\n\n*网络错误，请确认服务是否已启动。*'
  } finally {
    streamingStatus.value = ''
    streaming.value = false
    scrollBottom()
  }
}
</script>

<style scoped>
.chat-trigger {
  position: fixed;
  right: 32px;
  bottom: 140px;
  z-index: 100;
  display: flex;
  width: 148px;
  height: 54px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #fff;
  background: var(--atlas-primary);
  border: 1px solid var(--atlas-primary);
  border-radius: 5px;
  box-shadow: 0 8px 18px rgba(31,45,61,.18);
  cursor: pointer;
  transition: background .2s ease, border-color .2s ease, box-shadow .2s ease;
}

.chat-trigger:hover,
.chat-trigger.active {
  background: var(--atlas-primary-dark);
  border-color: var(--atlas-primary-dark);
  box-shadow: 0 10px 22px rgba(31,45,61,.22);
}

.trigger-icon {
  flex: 0 0 auto;
}

.trigger-label {
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}

.chat-panel {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 10000;
  display: flex;
  width: min(520px, 100vw);
  height: 100vh;
  flex-direction: column;
  background: var(--atlas-surface);
  border-left: 1px solid var(--atlas-border);
  border-top: 4px solid var(--atlas-primary);
  box-shadow: -18px 0 42px rgba(31,45,61,.16);
}

.chat-header {
  display: flex;
  min-height: 78px;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  border-bottom: 1px solid var(--atlas-border);
}

.header-left {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.header-icon {
  color: var(--atlas-primary);
}

.header-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-copy strong {
  color: var(--atlas-text);
  font-size: 15px;
  font-weight: 800;
}

.header-copy small {
  max-width: 280px;
  overflow: hidden;
  color: var(--atlas-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-badge {
  flex: 0 0 auto;
  padding: 4px 7px;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border-radius: 3px;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .04em;
}

.close-btn {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  color: var(--atlas-muted);
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.close-btn:hover {
  color: var(--atlas-text);
  background: var(--atlas-surface-soft);
}

.chat-scope-bar {
  padding: 12px 20px 13px;
  background: var(--atlas-bg);
  border-bottom: 1px solid var(--atlas-border);
}

.locked-scope,
.scope-picker {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.locked-scope span,
.scope-label {
  color: var(--atlas-primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.locked-scope strong {
  overflow: hidden;
  color: var(--atlas-text);
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.locked-scope small,
.scope-picker small {
  color: var(--atlas-muted);
  font-size: 11px;
  line-height: 1.45;
}

.scope-picker select {
  min-height: 40px;
  padding: 0 32px 0 11px;
  color: var(--atlas-text);
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border-strong);
  border-radius: 4px;
  outline: 0;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}

.scope-picker select:focus {
  border-color: var(--atlas-primary);
  box-shadow: 0 0 0 3px rgba(66,111,166,.12);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 22px 22px 24px;
}

.chat-empty {
  max-width: 390px;
  margin: 30px auto 0;
  padding: 28px 18px;
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-top: 2px solid var(--atlas-primary);
}

.empty-kicker {
  margin: 0 0 8px;
  color: var(--atlas-primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
}

.chat-empty h3 {
  margin: 0 0 12px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
}

.chat-empty p {
  margin: 0 0 18px;
  color: var(--atlas-muted);
  font-size: 13px;
  line-height: 1.6;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sug-chip {
  min-height: 38px;
  padding: 8px 11px;
  color: var(--atlas-primary);
  background: transparent;
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.sug-chip:hover {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-primary);
}

.msg-wrapper {
  display: flex;
  margin-bottom: 16px;
}

.msg-wrapper.user {
  justify-content: flex-end;
}

.msg-wrapper.assistant {
  justify-content: flex-start;
}

.msg-bubble {
  max-width: 91%;
  padding: 12px 15px;
  color: var(--atlas-text);
  background: var(--atlas-surface-soft);
  border-radius: 5px;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.msg-wrapper.user .msg-bubble {
  color: #fff;
  background: var(--atlas-primary);
  border-bottom-right-radius: 2px;
}

.msg-wrapper.assistant .msg-bubble {
  border-bottom-left-radius: 2px;
}

.msg-sources {
  margin-top: 13px;
  padding-top: 11px;
  border-top: 1px solid var(--atlas-border);
}

.sources-label {
  margin-bottom: 6px;
  color: var(--atlas-muted);
  font-size: 11px;
  font-weight: 800;
}

.source-item {
  margin: 8px 0 0;
  padding: 8px;
  background: rgba(255,255,255,.55);
  border: 1px solid var(--atlas-border);
  outline: none;
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}

.source-item:hover,
.source-item:focus-within,
.source-item:focus {
  background: rgba(255,255,255,.9);
  border-color: rgba(26,78,115,.28);
  box-shadow: 0 8px 20px rgba(19,42,61,.08);
}

.source-topline {
  display: flex;
  gap: 6px;
  align-items: baseline;
}

.source-topline strong {
  color: var(--atlas-primary);
  font-size: 12px;
}

.source-rank,
.source-meta {
  color: var(--atlas-muted);
  font-size: 10px;
}

.source-snippet {
  display: -webkit-box;
  margin-top: 4px;
  color: var(--atlas-muted);
  font-size: 11px;
  line-height: 1.45;
  max-height: 34px;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  cursor: default;
}

.source-item:hover .source-snippet,
.source-item:focus-within .source-snippet,
.source-item:focus .source-snippet {
  display: block;
  max-height: 180px;
  overflow: auto;
  color: var(--atlas-text);
  -webkit-line-clamp: unset;
}

.streaming-text {
  color: var(--atlas-muted);
  font-size: 12px;
}

.dot-pulse::after {
  content: '...';
  animation: dots 1.4s infinite;
}

@keyframes dots {
  0%, 20% { content: '.'; }
  40% { content: '..'; }
  60%, 100% { content: '...'; }
}

.chat-input {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 16px;
  background: var(--atlas-surface);
  border-top: 1px solid var(--atlas-border);
}

.input-context {
  display: flex;
  flex-basis: 100%;
  min-width: 0;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  color: var(--atlas-muted);
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  background: #3f7f5d;
  border-radius: 50%;
}

.chat-input-field {
  min-height: 44px;
  flex: 1;
  padding: 10px 14px;
  color: var(--atlas-text);
  background: var(--atlas-bg);
  border: 1px solid var(--atlas-border);
  border-radius: 3px;
  outline: none;
  font-size: 14px;
}

.chat-input-field:focus {
  border-color: var(--atlas-primary);
}

.chat-send-btn {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  color: #fff;
  background: var(--atlas-primary);
  border: none;
  border-radius: 3px;
  cursor: pointer;
}

.chat-send-btn:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
}

.chat-send-btn:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.chat-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0,0,0,.2);
}

@media (min-width: 521px) {
  .chat-overlay {
    display: none;
  }
}

.slide-enter-active {
  transition: transform .3s cubic-bezier(.16, 1, .3, 1);
}

.slide-leave-active {
  transition: transform .2s ease;
}

.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}

@media (max-width: 620px) {
  .chat-panel {
    width: 100vw;
  }

  .chat-messages {
    padding: 16px;
  }

  .chat-empty {
    margin-top: 12px;
  }

  .chat-trigger {
    right: 16px;
    bottom: 24px;
    width: 56px;
    height: 56px;
    padding: 0;
  }

  .chat-trigger .trigger-label {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .slide-enter-active,
  .slide-leave-active {
    transition: none;
  }
}
</style>
