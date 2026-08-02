<template>
  <div class="chat-widget" :class="{ home: isHome, 'project-scope': !!project }">
    <!-- 浮动触发按钮 -->
    <button class="chat-trigger" :class="{ active: panelOpen }" @click="togglePanel" title="打开 AI 对话" aria-label="打开 AI 对话">
      <svg class="trigger-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <path d="M4 5h16v12H7l-3 3z" />
        <path d="M8 9h8M8 13h5" />
      </svg>
      <span class="trigger-label">AI 对话</span>
    </button>

    <!-- 侧边聊天面板 -->
    <Teleport to="body">
      <transition name="slide">
        <div v-if="panelOpen" class="chat-panel">
          <!-- 头部 -->
          <div class="chat-header">
            <div class="header-left">
              <span class="header-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path d="M4 4h12v12H4z" />
                  <path d="M8 8h12v12H8z" />
                </svg>
              </span>
              <span class="header-title">AI 智能问答</span>
              <span class="header-badge">{{ project ? 'PROJECT' : 'RAG' }}</span>
              <span v-if="project" class="header-project-title">{{ project.name }}</span>
            </div>
            <button class="close-btn" @click="panelOpen = false">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <div class="chat-scope-bar">
            <label class="scope-picker">
              <span class="scope-label">对话项目</span>
              <select v-model="selectedProjectId" :disabled="streaming || projectsLoading" @change="handleProjectChange">
                <option value="">全局知识库（不绑定项目）</option>
                <option v-for="item in projects" :key="item.id" :value="String(item.id)">
                  {{ item.name }}
                </option>
              </select>
            </label>
            <span class="scope-hint">{{ project ? '回答将结合当前项目健康报告和交付证据' : '选择项目后，回答会自动绑定项目上下文' }}</span>
          </div>

          <!-- 消息列表 -->
          <div class="chat-messages" ref="msgList">
            <div v-if="messages.length === 0" class="chat-empty">
              <p class="empty-kicker">{{ project ? 'PROJECT AGENT' : 'KNOWLEDGE ASSISTANT' }}</p>
              <p class="empty-guidance">{{ project ? '围绕当前项目的健康、风险、证据和交付计划提问。' : '从 Agent 参考库中查找研发知识和项目经验。' }}</p>
              <div class="empty-icon" aria-hidden="true">
                <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
                  <path d="M4 5h16v11H7l-3 3z" />
                  <path d="M8 9h8M8 12h5" />
                </svg>
              </div>
              <p class="empty-text">基于企业知识库为你解答</p>
              <div class="suggestions">
                <button v-for="s in activeSuggestions" :key="s" class="sug-chip" @click="send(s)">{{ s }}</button>
              </div>
            </div>

            <div v-for="(msg, i) in messages" :key="i" class="msg-wrapper" :class="msg.role">
              <div class="msg-bubble">
                <div class="msg-content" v-html="renderMd(msg.content)"></div>
                <!-- 来源引用 -->
                <div v-if="msg.sources && msg.sources.length" class="msg-sources">
                  <div class="sources-label">📄 参考来源</div>
                  <div v-for="s in msg.sources" :key="sourceKey(s)" class="source-item">
                    <a
                      v-if="s.sourceUrl"
                      :href="s.sourceUrl"
                      target="_blank"
                      class="source-link"
                    >
                      #{{ s.rank || '-' }} {{ s.title }}
                    </a>
                    <span v-else class="source-link">
                      #{{ s.rank || '-' }} {{ s.title }}
                    </span>
                    <span class="source-meta">{{ s.sourceType || 'KNOWLEDGE' }} · score {{ formatScore(s.score) }}</span>
                    <span class="source-snippet">{{ s.snippet }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Streaming 指示器 -->
            <div v-if="streaming" class="msg-wrapper assistant">
              <div class="msg-bubble streaming">
                <span class="streaming-text" v-if="streamingStatus">{{ streamingStatus }}</span>
                <span class="dot-pulse" v-else></span>
              </div>
            </div>
          </div>

          <!-- 输入区 -->
          <div class="chat-input">
            <div v-if="project" class="input-context" title="本次对话将使用当前项目上下文">
              <span class="context-dot"></span>
              <span>{{ project.name }}</span>
            </div>
            <input
              v-model="inputText"
              class="chat-input-field"
              :placeholder="project ? '围绕当前项目提问健康、风险或交付计划...' : '输入问题，基于企业知识库回答...'"
              @keydown.enter="send()"
              :disabled="streaming"
            />
            <button class="chat-send-btn" @click="send()" :disabled="streaming || !inputText.trim()">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
            </button>
          </div>
        </div>
      </transition>
    </Teleport>

    <!-- 面板打开时的遮罩（移动端） -->
    <div v-if="panelOpen" class="chat-overlay" @click="panelOpen = false"></div>
  </div>
</template>

<script setup>
import { computed, ref, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { createAiSession, getAiSessionMessages, listContracts } from '../api/index.js'

const panelOpen = ref(false)
const route = useRoute()
const isHome = computed(() => route.path === '/')
const project = ref(null)
const projects = ref([])
const projectsLoading = ref(false)
const selectedProjectId = ref('')
const inputText = ref('')
const messages = ref([])
const streaming = ref(false)
const streamingStatus = ref('')
const suggestions = ref([
  '这个知识库主要包含哪些内容？',
  'Spring Boot怎么部署？',
  'MySQL索引如何优化？',
  'Vue 3有什么新特性？',
])
const msgList = ref(null)
const sessionId = ref(null)
const sessionToken = ref('')
const projectSuggestions = [
  '当前项目的主要风险是什么？',
  '下一步交付计划应该怎么排？',
  '这份健康报告有哪些证据支持？',
  '当前里程碑是否存在延期风险？',
]
const activeSuggestions = computed(() => project.value ? projectSuggestions : suggestions.value)

const sessionStorageKey = computed(() => 'atlasmind-chat-session-' + (project.value?.id || 'global'))

onMounted(async () => {
  const storedProject = localStorage.getItem('atlasmind-chat-project')
  let parsedStoredProject = null
  if (storedProject) {
    try { parsedStoredProject = JSON.parse(storedProject) } catch { localStorage.removeItem('atlasmind-chat-project') }
  }
  await loadProjects()
  const routeProject = findProject(route.params.id)
  if (routeProject) {
    project.value = normalizeProject(routeProject)
    selectedProjectId.value = String(routeProject.id)
  } else if (parsedStoredProject?.id) {
    project.value = normalizeProject(parsedStoredProject)
    selectedProjectId.value = String(parsedStoredProject.id)
  }
  await restoreSession()
  window.addEventListener('atlasmind:open-chat', handleOpenChat)
})

onBeforeUnmount(() => {
  window.removeEventListener('atlasmind:open-chat', handleOpenChat)
})

watch(() => route.params.id, async (routeId) => {
  const routeProject = findProject(routeId)
  if (routeProject && String(project.value?.id || '') !== String(routeProject.id)) {
    await applyProject(routeProject)
  }
})

function togglePanel() {
  panelOpen.value = !panelOpen.value
  if (panelOpen.value && messages.value.length === 0) {
    loadSuggestions()
  }
}

async function handleOpenChat(event) {
  const nextProject = event.detail || null
  const currentId = project.value?.id
  const nextId = nextProject?.projectId
  if (String(currentId || '') !== String(nextId || '')) {
    await applyProject(findProject(nextId) || (nextId ? { id: nextId, name: nextProject.projectName || '当前项目' } : null))
  }
  panelOpen.value = true
  if (!messages.value.length) loadSuggestions()
}

async function loadProjects() {
  projectsLoading.value = true
  try {
    const response = await listContracts()
    const cases = response.data.data || []
    projects.value = cases.map(c => ({ id: c.id, name: c.title || c.caseKey }))
  } catch {
    projects.value = []
  } finally {
    projectsLoading.value = false
  }
}

function normalizeProject(value) {
  return value ? { id: value.id, name: value.name || '当前项目' } : null
}

function findProject(projectId) {
  if (!projectId) return null
  return projects.value.find(item => String(item.id) === String(projectId)) || null
}

async function handleProjectChange() {
  await applyProject(findProject(selectedProjectId.value))
}

async function applyProject(nextProject) {
  const next = normalizeProject(nextProject)
  if (String(project.value?.id || '') === String(next?.id || '')) return

  project.value = next
  selectedProjectId.value = next ? String(next.id) : ''
  sessionId.value = null
  sessionToken.value = ''
  messages.value = []
  inputText.value = ''
  localStorage.removeItem('atlasmind-chat-project')
  if (project.value) {
    localStorage.setItem('atlasmind-chat-project', JSON.stringify(project.value))
  }
  await restoreSession()
}

async function loadSuggestions() {
  try {
    const res = await fetch('/api/chat/suggestions')
    if (res.ok) {
      const data = await res.json()
      if (data.suggestions) suggestions.value = data.suggestions
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
    messages.value = (response.data.data || []).map((message) => ({
      role: message.role,
      content: message.content,
      sources: []
    }))
  } catch {
    localStorage.removeItem(sessionStorageKey.value)
    localStorage.removeItem(sessionStorageKey.value + '-token')
  }
}

async function ensureSession() {
  if (sessionId.value) return sessionId.value
  try {
    const response = await createAiSession({
      source: project.value ? 'PROJECT_ASSISTANT' : 'KNOWLEDGE_ASSISTANT',
      scope: project.value ? 'PROJECT' : 'GLOBAL',
      projectId: project.value?.id || null
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
  if (!text) return ''
  return marked.parse(text, { breaks: true })
}

function formatScore(value) {
  const score = Number(value || 0)
  return score ? score.toFixed(3) : '0'
}

function sourceKey(source) {
  return `${source.sourceType || 'KNOWLEDGE'}-${source.sourceId || source.id || 'x'}-${source.chunkId || 'root'}-${source.rank || 0}`
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
  streamingStatus.value = '正在检索...'

  try {
    const history = messages.value.slice(0, -1).map(m => ({ role: m.role, content: m.content }))
    const response = await fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        history,
        sessionId: activeSessionId,
        ownerToken: sessionToken.value,
        projectId: project.value?.id || null
      }),
    })

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let eventType = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            if (eventType === 'status') {
              streamingStatus.value = data.status === 'thinking' ? '正在生成回复...' : (data.status === 'searching' ? '正在检索...' : data.status)
            } else if (eventType === 'chunk') {
              streamingStatus.value = ''
              assistantMsg.content += data.content
              scrollBottom()
            } else if (eventType === 'sources') {
              assistantMsg.sources = data.sources
              assistantMsg.traceId = data.traceId
            } else if (eventType === 'done') {
              // noop
            } else if (eventType === 'error') {
              assistantMsg.content += '\n\n*抱歉，出错了：' + data.error + '*'
            }
          } catch {}
        }
      }
    }
  } catch (e) {
    assistantMsg.content += '\n\n*网络错误，请确认服务是否启动*'
  } finally {
    streamingStatus.value = ''
    streaming.value = false
    scrollBottom()
  }
}
</script>

<style scoped>
/* ====== 触发按钮 ====== */
.chat-trigger {
  position: fixed;
  bottom: 140px;
  right: 32px;
  z-index: 100;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.5);
  background: rgba(255,255,255,0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s ease;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.chat-trigger:hover, .chat-trigger.active {
  transform: translateY(-2px);
  border-color: #426fa6;
  box-shadow: 0 4px 16px rgba(99,102,241,0.3);
}
.trigger-icon { font-size: 20px; line-height: 1; }

/* ====== 侧边面板 ====== */
.chat-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 420px;
  max-width: 100vw;
  height: 100vh;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border-left: 1px solid rgba(0,0,0,0.08);
  box-shadow: -4px 0 32px rgba(0,0,0,0.1);
}

/* ====== 头部 ====== */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(0,0,0,0.06);
}
.header-left { display: flex; align-items: center; gap: 8px; }
.header-icon { font-size: 20px; }
.header-title { font-size: 15px; font-weight: 600; color: #1e293b; }
.header-badge {
  font-size: 10px; font-weight: 600; color: #426fa6;
  background: rgba(99,102,241,0.1); padding: 2px 8px; border-radius: 8px;
}
.close-btn {
  width: 32px; height: 32px; border-radius: 8px; border: none;
  background: transparent; cursor: pointer; display: flex;
  align-items: center; justify-content: center; color: #94a3b8;
}
.close-btn:hover { background: rgba(0,0,0,0.05); color: #475569; }

/* ====== 消息区 ====== */
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.chat-messages::-webkit-scrollbar { width: 4px; }
.chat-messages::-webkit-scrollbar-thumb {
  background: rgba(0,0,0,0.1); border-radius: 2px;
}

/* 空状态 */
.chat-empty { text-align: center; padding: 40px 16px; }
.empty-icon { font-size: 48px; margin-bottom: 12px; }
.empty-text { color: #94a3b8; font-size: 13px; margin-bottom: 20px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.sug-chip {
  padding: 6px 14px; border-radius: 16px; border: 1px solid rgba(99,102,241,0.25);
  background: rgba(99,102,241,0.05); color: #426fa6;
  font-size: 12px; cursor: pointer; transition: all 0.2s;
}
.sug-chip:hover { background: rgba(99,102,241,0.15); border-color: #426fa6; }

/* 消息气泡 */
.msg-wrapper { margin-bottom: 16px; display: flex; }
.msg-wrapper.user { justify-content: flex-end; }
.msg-wrapper.assistant { justify-content: flex-start; }

.msg-bubble {
  max-width: 88%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
.msg-wrapper.user .msg-bubble {
  background: var(--atlas-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg-wrapper.assistant .msg-bubble {
  background: rgba(0,0,0,0.04);
  color: #334155;
  border-bottom-left-radius: 4px;
}

/* 来源引用 */
.msg-sources {
  margin-top: 8px; padding-top: 8px;
  border-top: 1px solid rgba(0,0,0,0.06);
}
.sources-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.source-item { display: flex; flex-direction: column; gap: 2px; margin-bottom: 7px; }
.source-link { font-size: 12px; color: #426fa6; text-decoration: none; }
.source-link:hover { text-decoration: underline; }
.source-meta { font-size: 10px; color: #94a3b8; }
.source-snippet { font-size: 11px; color: #94a3b8; line-height: 1.45; }

/* Streaming 动画 */
.streaming-text {
  font-size: 12px;
  color: #94a3b8;
}
.streaming .dot-pulse::after {
  content: '...';
  animation: dots 1.4s infinite;
}
@keyframes dots {
  0%, 20% { content: '.'; }
  40% { content: '..'; }
  60%, 100% { content: '...'; }
}

/* ====== 输入区 ====== */
.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid rgba(0,0,0,0.06);
  background: rgba(255,255,255,0.6);
}
.chat-input-field {
  flex: 1;
  padding: 10px 14px;
  border-radius: 12px;
  border: 1px solid rgba(0,0,0,0.1);
  background: rgba(0,0,0,0.03);
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s;
}
.chat-input-field:focus { border-color: #426fa6; }
.chat-send-btn {
  width: 40px; height: 40px; border-radius: 12px; border: none;
  background: #426fa6; color: #fff; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.2s;
}
.chat-send-btn:hover:not(:disabled) { background: #315987; transform: scale(1.05); }
.chat-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ====== 遮罩 ====== */
.chat-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0,0,0,0.2);
}
@media (min-width: 421px) { .chat-overlay { display: none; } }

/* ====== 动画 ====== */
.slide-enter-active { transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.slide-leave-active { transition: all 0.2s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }

/* ====== 暗色模式 ====== */
[data-theme="dark"] .chat-trigger {
  background: rgba(30,41,59,0.8); border-color: rgba(255,255,255,0.1);
}
[data-theme="dark"] .chat-panel {
  background: rgba(15,23,42,0.95); border-color: rgba(255,255,255,0.06);
}
[data-theme="dark"] .chat-header { border-color: rgba(255,255,255,0.06); }
[data-theme="dark"] .header-title { color: #e2e8f0; }
[data-theme="dark"] .msg-wrapper.assistant .msg-bubble {
  background: rgba(255,255,255,0.06); color: #cbd5e1;
}
[data-theme="dark"] .chat-input-field {
  background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1);
  color: #e2e8f0;
}
[data-theme="dark"] .chat-input { background: rgba(15,23,42,0.6); }
[data-theme="dark"] .sug-chip { background: rgba(99,102,241,0.1); }
[data-theme="dark"] .msg-sources { border-color: rgba(255,255,255,0.06); }
[data-theme="dark"] .chat-overlay { background: rgba(0,0,0,0.5); }

/* Hallmark | Workbench surface: blue ink, paper surfaces, no decorative gradients */
.chat-trigger {
  border-color: var(--atlas-border);
  background: var(--atlas-surface);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  box-shadow: 0 2px 8px rgba(31, 45, 61, 0.08);
}

.chat-trigger:hover,
.chat-trigger.active {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
  box-shadow: 0 2px 8px rgba(31, 45, 61, 0.08);
  transform: none;
}

.trigger-icon {
  display: block;
  font-size: 0;
}

.chat-panel {
  background: var(--atlas-surface);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-left-color: var(--atlas-border);
  box-shadow: -8px 0 28px rgba(31, 45, 61, 0.08);
}

.header-icon {
  color: var(--atlas-primary);
}

.header-badge {
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border-radius: 3px;
}

.sug-chip {
  border-color: var(--atlas-border);
  border-radius: 3px;
  background: transparent;
  color: var(--atlas-primary);
}

.sug-chip:hover {
  background: var(--atlas-surface-soft);
  border-color: var(--atlas-primary);
}

.msg-wrapper.user .msg-bubble {
  background: var(--atlas-primary);
}

.msg-wrapper.assistant .msg-bubble {
  background: var(--atlas-surface-soft);
}

.chat-input {
  background: var(--atlas-surface);
}

.chat-input-field {
  border-radius: 3px;
  border-color: var(--atlas-border);
  background: var(--atlas-bg);
}

.chat-input-field:focus {
  border-color: var(--atlas-primary);
}

.chat-send-btn {
  border-radius: 3px;
  background: var(--atlas-primary);
}

.chat-send-btn:hover:not(:disabled) {
  background: var(--atlas-primary-dark);
  transform: none;
}
.chat-widget.home .chat-trigger { display: none; }
.chat-widget.project-scope .header-title { display: none; }
.header-project-title {
  display: block;
  color: var(--atlas-text);
  font-size: 15px;
  font-weight: 800;
}
.chat-panel {
  width: min(520px, 100vw);
  border-top: 4px solid var(--atlas-primary);
  box-shadow: -18px 0 42px rgba(31,45,61,.16);
}
.chat-header {
  min-height: 78px;
  padding: 15px 20px;
}
.header-left { min-width: 0; }
.header-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 3px;
}
.header-context {
  max-width: 260px;
  overflow: hidden;
  color: var(--atlas-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-badge {
  flex: 0 0 auto;
  padding: 4px 7px;
  font-size: 10px;
  letter-spacing: .04em;
}
.close-btn {
  width: 44px;
  height: 44px;
  border-radius: 4px;
}
.chat-scope-bar {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px 20px 13px;
  background: var(--atlas-bg);
  border-bottom: 1px solid var(--atlas-border);
}
.scope-picker {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 5px;
}
.scope-label {
  color: var(--atlas-primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.scope-picker select {
  width: 100%;
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
.scope-picker select:disabled {
  cursor: wait;
  opacity: .65;
}
.scope-hint {
  max-width: 170px;
  padding-bottom: 4px;
  color: var(--atlas-muted);
  font-size: 11px;
  line-height: 1.45;
}
.chat-messages { padding: 22px 22px 24px; }
.chat-empty {
  max-width: 390px;
  margin: 30px auto 0;
  padding: 28px 18px;
  border: 1px solid var(--atlas-border);
  border-top: 2px solid var(--atlas-primary);
  background: var(--atlas-bg);
}
.empty-icon {
  display: grid;
  width: 58px;
  height: 58px;
  margin: 0 auto 18px;
  place-items: center;
  color: var(--atlas-primary);
  background: var(--atlas-surface-soft);
  border: 1px solid var(--atlas-border);
  border-radius: 5px;
}
.empty-kicker {
  margin: 0 0 8px;
  color: var(--atlas-primary);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .08em;
}
.empty-guidance {
  margin: 0 0 20px;
  color: var(--atlas-text);
  font-family: var(--atlas-font-display);
  font-size: 22px;
  line-height: 1.3;
}
.empty-text { display: none; }
.suggestions { justify-content: flex-start; }
.sug-chip {
  min-height: 38px;
  padding: 8px 11px;
  border-radius: 4px;
  font-size: 12px;
  text-align: left;
}
.msg-bubble {
  max-width: 91%;
  padding: 12px 15px;
  border-radius: 5px;
  font-size: 14px;
  line-height: 1.7;
}
.msg-wrapper.user .msg-bubble { border-bottom-right-radius: 2px; }
.msg-wrapper.assistant .msg-bubble { border-bottom-left-radius: 2px; }
.msg-sources {
  margin-top: 13px;
  padding-top: 11px;
}
.source-item {
  margin: 8px 0 0;
  padding: 8px;
  background: rgba(255,255,255,.55);
  border: 1px solid var(--atlas-border);
}
.chat-input {
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px 16px;
}
.input-context {
  display: flex;
  flex-basis: 100%;
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
  border-radius: 50%;
  background: #3f7f5d;
}
.chat-input-field {
  min-height: 44px;
  font-size: 14px;
}
.chat-send-btn {
  width: 44px;
  height: 44px;
}
.chat-trigger {
  width: 148px;
  height: 54px;
  gap: 9px;
  padding: 0 16px;
  border-radius: 5px;
  background: var(--atlas-primary);
  color: #fff;
  border-color: var(--atlas-primary);
  box-shadow: 0 8px 18px rgba(31,45,61,.18);
}
.chat-trigger:hover,
.chat-trigger.active {
  color: #fff;
  background: var(--atlas-primary-dark);
  border-color: var(--atlas-primary-dark);
  box-shadow: 0 10px 22px rgba(31,45,61,.22);
}
.trigger-icon {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
}
.trigger-label {
  font-size: 13px;
  font-weight: 800;
  white-space: nowrap;
}
@media (max-width: 620px) {
  .chat-panel { width: 100vw; }
  .chat-messages { padding: 16px; }
  .chat-empty { margin-top: 12px; }
  .chat-trigger { right: 16px; bottom: 24px; width: 56px; height: 56px; padding: 0; }
  .chat-trigger .trigger-label { display: none; }
  .chat-scope-bar { align-items: stretch; flex-direction: column; gap: 7px; }
  .scope-hint { max-width: none; padding-bottom: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .slide-enter-active,
  .slide-leave-active { transition: none; }
}
</style>
