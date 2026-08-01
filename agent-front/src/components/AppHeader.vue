<template>
  <header class="header" :class="{ scrolled }">
    <div class="header-inner">
      <router-link to="/" class="logo">
        <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true"><path d="M4 4h16v16H4z"/><path d="M8 8h16v16H8z"/></svg>
        <span class="logo-text">AtlasMind</span>
      </router-link>
      <nav class="nav">
        <router-link to="/" class="nav-link"><span class="nav-label">工作台</span></router-link>
        <router-link to="/knowledge" class="nav-link"><span class="nav-label">Agent 参考库</span></router-link>
      </nav>
      <div class="search-box" @submit.prevent="doSearch">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input v-model="keyword" type="text" class="search-input" placeholder="搜索项目或证据..." @keyup.enter="doSearch"/>
      </div>
      <div class="header-actions">
        <!-- 消息中心 -->
        <div class="notification-wrap" @click.stop>
          <button type="button" class="notification-button" title="消息中心" aria-label="消息中心" @click="toggleNotificationPanel">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
            <span v-if="unreadCount > 0" class="notification-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </button>
          <div v-if="notificationOpen" class="notification-panel" @click.stop @wheel.stop>
            <!-- 外部模型状态（最顶部） -->
            <div class="panel-section-heading">
              <strong>外部模型状态</strong>
              <button type="button" class="icon-refresh" title="重新检测" :disabled="aiStatusLoading" @click="refreshAiStatus">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8.1 8.1 0 0 0-14.8-4L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8.1 8.1 0 0 0 14.8 4L21 15"/><path d="M21 20v-5h-5"/></svg>
              </button>
            </div>
            <div class="model-status-list">
              <div v-for="item in modelStatusItems" :key="item.key" class="model-status-row">
                <span>{{ item.label }}</span>
                <strong :class="statusClass(item.status)">{{ statusLabel(item.status) }}</strong>
              </div>
            </div>
            <p v-if="aiStatusMessage" class="status-message">{{ aiStatusMessage }}</p>
            <time v-if="aiStatus?.checkedAt" class="checked-time">检测于 {{ formatTime(aiStatus.checkedAt) }}</time>

            <div class="panel-divider"></div>

            <!-- Agent 运行中心 -->
            <div class="panel-section-heading">
              <strong>Agent 运行中心</strong>
              <span class="section-note">自动刷新</span>
            </div>
            <RunFeed :runs="recentRuns" :max-items="8" compact :polling="notificationOpen" empty-text="暂无运行记录" @status-change="onRunStatusChange"/>
          </div>
        </div>
        <a class="admin-link" :href="adminUrl" target="_blank" rel="noreferrer">管理端</a>
        <button type="button" class="logout-button" @click="logout">退出</button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getRecentWorkspaceRuns, getWorkspaceAiStatus, getWorkspaceUnreadCount } from '../api/index.js'
import RunFeed from './RunFeed.vue'

const router = useRouter()
const message = useMessage()
const keyword = ref('')
const scrolled = ref(false)
const adminUrl = import.meta.env.VITE_ADMIN_URL || 'http://localhost:15173/'
const notificationOpen = ref(false)
const unreadCount = ref(0)
const aiStatus = ref(null)
const aiStatusLoading = ref(false)
const recentRuns = ref([])
let refreshTimer = null

const modelStatusItems = computed(() => {
  const components = aiStatus.value?.components || {}
  return [
    { key: 'llm', label: 'LLM / DeepSeek', status: components.llm?.status || 'unknown' },
    { key: 'embedding', label: 'Embedding', status: components.embedding?.status || 'unknown' },
    { key: 'elasticsearch', label: 'Elasticsearch', status: components.elasticsearch?.status || 'unknown' }
  ]
})
const aiStatusMessage = computed(() => {
  const components = aiStatus.value?.components || {}
  return Object.values(components).find(item => item?.message)?.message || ''
})

if (typeof window !== 'undefined') {
  window.addEventListener('scroll', () => { scrolled.value = window.scrollY > 10 })
}

onMounted(() => {
  refreshHeaderData(); refreshAiStatus()
  document.addEventListener('click', closeNotificationPanel)
  refreshTimer = window.setInterval(refreshAll, 8000)
})
onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  document.removeEventListener('click', closeNotificationPanel)
})

async function refreshAll() {
  try {
    const [countRes, runsRes] = await Promise.allSettled([
      getWorkspaceUnreadCount(),
      getRecentWorkspaceRuns()
    ])
    if (countRes.status === 'fulfilled') unreadCount.value = Number(countRes.value.data.data?.count) || 0
    if (runsRes.status === 'fulfilled') recentRuns.value = runsRes.value.data.data || []
  } catch { /* silent */ }
}
async function refreshHeaderData() {
  try { const r = await getWorkspaceUnreadCount(); unreadCount.value = Number(r.data.data?.count) || 0 } catch {}
  if (notificationOpen.value) {
    try { const r = await getRecentWorkspaceRuns(); recentRuns.value = r.data.data || [] } catch {}
  }
}
async function refreshAiStatus() {
  aiStatusLoading.value = true
  try { const r = await getWorkspaceAiStatus(); aiStatus.value = r.data.data || null }
  catch { aiStatus.value = { status:'error', components:{ llm:{status:'error',message:'无法连接'} } } }
  finally { aiStatusLoading.value = false }
}

function doSearch() { router.push({ path:'/', query: keyword.value.trim() ? { keyword: keyword.value } : {} }) }
function logout() { localStorage.removeItem('atlasmind-token'); router.push('/login') }

async function toggleNotificationPanel() {
  notificationOpen.value = !notificationOpen.value
  if (notificationOpen.value) { await refreshHeaderData(); if (!aiStatus.value) await refreshAiStatus() }
}
function closeNotificationPanel() { notificationOpen.value = false }

function onRunStatusChange({ run }) {
  const label = { HEALTH_ANALYSIS:'健康分析', PROJECT_ONBOARDING:'项目接手', ENGINEERING_DECISION:'研发决策' }[run.runType] || 'Agent 任务'
  if (run.status === 'COMPLETED') message.success(`${label}已完成 — ${run.projectName || ('项目 #'+run.projectId)}`)
  else if (run.status === 'FAILED') message.error(`${label}失败 — ${run.projectName || ('项目 #'+run.projectId)}`)
}

function formatTime(v) { if (!v) return '刚刚'; const d = new Date(v); return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('zh-CN',{hour12:false}) }
function statusLabel(s) { return { ok:'可用', configured:'已配置', checking:'检测中', error:'不可用', degraded:'异常', info:'未配置', unknown:'未检测' }[String(s||'').toLowerCase()] || String(s||'未检测') }
function statusClass(s) { const n = String(s||'').toLowerCase(); if (['ok','completed','done'].includes(n)) return 'ok'; if (['error','failed'].includes(n)) return 'error'; if (['checking','created','context_building','analyzing','verifying','planning'].includes(n)) return 'checking'; return 'unknown' }
</script>

<style scoped>
.header{position:sticky;top:0;z-index:100;background:rgba(247,248,251,.88);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--atlas-border);transition:box-shadow .25s,background .25s}
.header.scrolled{background:rgba(255,255,255,.94);box-shadow:0 8px 24px rgba(15,23,42,.06)}
.header-inner{max-width:1120px;margin:0 auto;padding:0 24px;display:flex;justify-content:space-between;align-items:center;height:60px;gap:24px;box-sizing:border-box}
.logo{display:flex;align-items:center;gap:8px;text-decoration:none}
.logo-mark{width:30px;height:30px;flex:0 0 auto;fill:none;stroke:var(--atlas-primary);stroke-width:2;stroke-linejoin:round}
.logo-text{color:var(--atlas-text);font-family:Georgia,'Times New Roman',serif;font-size:19px;font-weight:700}
.nav{display:flex;gap:2px;flex:1;min-width:0;justify-content:center}
.nav-link{padding:7px 12px;border-radius:6px;text-decoration:none;font-size:14px;color:var(--atlas-muted);transition:all .15s}
.nav-link:hover{background:var(--atlas-surface-soft);color:var(--atlas-text)}
.nav-link.router-link-active{color:var(--atlas-primary);font-weight:700;box-shadow:inset 0 -2px 0 var(--atlas-primary)}
.search-box{display:flex;align-items:center;gap:6px;height:34px;padding:0 10px;border-radius:4px;background:var(--atlas-surface);border:1px solid var(--atlas-border);transition:border-color .2s,box-shadow .2s;min-width:0}
.search-box:focus-within{border-color:var(--atlas-primary);box-shadow:0 0 0 3px rgba(66,111,166,.12)}
.search-icon{color:#c0c4cc;flex-shrink:0;transition:color .2s}
.search-box:focus-within .search-icon{color:var(--atlas-primary)}
.search-input{border:none;outline:none;background:transparent;font-size:13px;color:var(--atlas-text);width:130px;font-family:inherit}
.search-input::placeholder{color:#c0c4cc}
.header-actions{display:flex;align-items:center;gap:8px;flex:0 0 auto}

/* Notification */
.notification-wrap{position:relative}
.notification-button,.icon-refresh{display:inline-flex;align-items:center;justify-content:center;position:relative;border:1px solid var(--atlas-border);background:var(--atlas-surface);color:var(--atlas-muted);cursor:pointer}
.notification-button{width:34px;height:34px;border-radius:4px}
.notification-button:hover,.icon-refresh:hover:not(:disabled){color:var(--atlas-primary);border-color:var(--atlas-primary)}
.notification-badge{position:absolute;top:-6px;right:-6px;min-width:16px;height:16px;padding:0 4px;border-radius:8px;background:#b35c56;color:#fff;font-size:9px;font-weight:800;line-height:16px;text-align:center}
.notification-panel{position:absolute;top:calc(100% + 10px);right:0;z-index:110;width:390px;max-width:calc(100vw - 32px);max-height:min(580px, calc(100vh - 86px));overflow-y:auto;overflow-x:hidden;padding:14px;background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;box-shadow:0 14px 30px rgba(15,23,42,.14)}
.panel-section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.panel-section-heading strong{color:var(--atlas-text);font-size:13px}
.section-note{color:var(--atlas-subtle);font-size:10px}
.panel-divider{height:1px;margin:14px 0;background:var(--atlas-border)}
.icon-refresh{width:26px;height:26px;border-radius:4px}
.icon-refresh:disabled{cursor:wait;opacity:.55}
.model-status-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:10px}
.model-status-row{min-width:0;padding:8px;border:1px solid var(--atlas-border);background:var(--atlas-bg)}
.model-status-row span{display:block;overflow:hidden;color:var(--atlas-muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}
.model-status-row strong{display:block;margin-top:4px;font-size:11px}
.model-status-row strong.ok{color:#3f7f5d}.model-status-row strong.error{color:#b35c56}.model-status-row strong.checking{color:var(--atlas-warning)}.model-status-row strong.unknown{color:var(--atlas-subtle)}
.status-message{margin:8px 0 0;color:#b35c56;font-size:10px;line-height:1.5;overflow-wrap:anywhere}
.checked-time{display:block;margin-top:8px;color:var(--atlas-subtle);font-size:10px}

.admin-link,.logout-button{display:inline-flex;align-items:center;justify-content:center;min-height:34px;padding:0 10px;color:var(--atlas-muted);background:var(--atlas-surface);border:1px solid var(--atlas-border);border-radius:4px;cursor:pointer;font-size:12px;font-weight:800;text-decoration:none;white-space:nowrap}
.admin-link:hover,.logout-button:hover{color:var(--atlas-primary);border-color:var(--atlas-primary)}

@media(max-width:860px){.header-inner{height:auto;min-height:60px;flex-wrap:wrap;gap:10px;padding:12px 16px}.nav{order:3;flex:0 0 100%;width:100%;min-width:0;overflow-x:auto;justify-content:flex-start;padding-bottom:2px}.nav-link{white-space:nowrap}.search-box{margin-left:auto;max-width:min(172px,calc(100vw - 190px))}.search-input{width:100%;min-width:0}}
@media(max-width:520px){.model-status-list{grid-template-columns:1fr}}
@media(max-width:420px){.header-inner{align-items:flex-start}.logo{min-height:34px}.search-box{order:2;flex:1 1 calc(100% - 96px);width:auto;max-width:none;margin-left:0}.header-actions{order:2;margin-left:auto}.notification-panel{position:fixed;top:70px;right:16px}.nav{order:3}}

[data-theme="dark"] .header{background:rgba(11,17,32,.88);border-bottom-color:var(--atlas-border)}
[data-theme="dark"] .header.scrolled{background:rgba(17,24,39,.94)}
[data-theme="dark"] .logo-mark{stroke:#8fb1d8}
[data-theme="dark"] .nav-link.router-link-active{color:#8fb1d8}
[data-theme="dark"] .search-box{background:var(--atlas-surface);border-color:var(--atlas-border)}
</style>
