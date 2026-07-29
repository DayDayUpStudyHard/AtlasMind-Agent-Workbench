<template>
  <div class="layout-root">
    <el-container class="layout">
      <el-aside width="220px" class="sidebar">
        <div class="sidebar-inner">
          <div class="logo">
            <router-link to="/" class="logo-link">
              <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true">
                <path d="M4 4h16v16H4z" />
                <path d="M8 8h16v16H8z" />
              </svg>
              <span class="logo-copy">
                <span class="logo-text">AtlasMind</span>
                <span class="logo-subtitle">Content Studio</span>
              </span>
            </router-link>
          </div>

          <el-menu :default-active="route.path" router class="menu">
            <el-menu-item index="/">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
                </span>
                <span class="menu-label">仪表盘</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/articles">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                </span>
                <span class="menu-label">文章管理</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/categories">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                </span>
                <span class="menu-label">分类管理</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/tags">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
                </span>
                <span class="menu-label">标签管理</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/comments">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                </span>
                <span class="menu-label">留言管理</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/moments">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                </span>
                <span class="menu-label">说说管理</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/knowledge">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/><path d="M8 7h8"/><path d="M8 11h6"/></svg>
                </span>
                <span class="menu-label">知识库</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/ai-observability">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 3v18h18"/><path d="M7 15l3-3 3 2 5-7"/><path d="M18 7h-4"/><path d="M18 7v4"/></svg>
                </span>
                <span class="menu-label">AI Observability</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/about-page">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                </span>
                <span class="menu-label">关于页面</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/logs">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                </span>
                <span class="menu-label">操作日志</span>
              </template>
            </el-menu-item>
            <el-menu-item index="/settings">
              <template #title>
                <span class="menu-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                </span>
                <span class="menu-label">个人设置</span>
              </template>
            </el-menu-item>
          </el-menu>

          <div class="sidebar-footer">
            <div class="user-row">
              <div class="user-avatar">
                <span>{{ userStore.avatarLetter }}</span>
              </div>
              <div class="user-meta">
                <span class="user-name">{{ userStore.displayName || 'Admin' }}</span>
                <span class="user-role">管理员</span>
              </div>
              <div class="status-dot" title="在线"></div>
            </div>
          </div>
        </div>
      </el-aside>

      <el-container class="right-area">
        <el-header class="topbar">
          <div class="topbar-left">
            <span class="topbar-path">{{ pageTitle }}</span>
          </div>
          <div class="topbar-actions">
            <el-popover placement="bottom-end" width="320" trigger="click" @show="fetchNotifications">
              <template #reference>
                <button class="theme-toggle notification-btn" title="消息中心">
                  <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
                  </el-badge>
                </button>
              </template>
              <div class="notification-panel">
                <div class="notification-head">
                  <strong>消息中心</strong>
                  <button @click="markAllRead">全部已读</button>
                </div>
                <div v-if="notifications.length === 0" class="notification-empty">暂无通知</div>
                <button
                  v-for="item in notifications"
                  :key="item.id"
                  class="notification-item"
                  :class="{ unread: item.readStatus === 0 }"
                  @click="markRead(item)"
                >
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.content }}</span>
                </button>
              </div>
            </el-popover>
            <button class="theme-toggle" @click="themeStore.toggle" :title="themeStore.isDark ? '切换亮色模式' : '切换暗色模式'">
              <svg v-if="!themeStore.isDark" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
              <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            </button>
            <a :href="portalFrontUrl" target="_blank" class="action-btn" title="查看知识门户">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
              <span>查看知识门户</span>
            </a>
            <button class="logout-btn" @click="logout" title="退出登录">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            </button>
          </div>
        </el-header>
        <el-main class="main-area">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user.js'
import { useThemeStore } from '../stores/theme.js'
import { getKbNotifications, getKbUnreadCount, readAllKbNotifications, readKbNotification } from '../api/index.js'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const themeStore = useThemeStore()
const portalFrontUrl = (import.meta.env.VITE_PORTAL_FRONT || '') + '/'
const unreadCount = ref(0)
const notifications = ref([])
let notificationTimer = null

const pageTitle = computed(() => {
  const map = {
    '/': '仪表盘',
    '/articles': '文章管理',
    '/articles/create': '新建文章',
    '/categories': '分类管理',
    '/tags': '标签管理',
    '/comments': '留言管理',
    '/moments': '说说管理',
    '/knowledge': '知识库',
    '/about-page': '关于页面',
    '/logs': '操作日志',
    '/settings': '个人设置',
  }
  if (route.path.startsWith('/articles/') && route.path.endsWith('/edit')) return '编辑文章'
  if (route.path === '/ai-observability') return 'AI Observability'
  return map[route.path] || ''
})

onMounted(async () => {
  try {
    await userStore.fetchUserInfo()
    await fetchUnreadCount()
    notificationTimer = window.setInterval(fetchUnreadCount, 8000)
  } catch { userStore.logout(); router.push('/login') }
})

onBeforeUnmount(() => {
  if (notificationTimer) window.clearInterval(notificationTimer)
})

function logout() {
  userStore.logout()
  router.push('/login')
}

async function fetchUnreadCount() {
  try {
    const res = await getKbUnreadCount()
    unreadCount.value = Number(res.data.data?.count) || 0
  } catch {}
}

async function fetchNotifications() {
  const res = await getKbNotifications()
  notifications.value = res.data.data || []
  await fetchUnreadCount()
}

async function markRead(item) {
  await readKbNotification(item.id)
  item.readStatus = 1
  await fetchUnreadCount()
}

async function markAllRead() {
  await readAllKbNotifications()
  notifications.value = notifications.value.map(item => ({ ...item, readStatus: 1 }))
  await fetchUnreadCount()
}
</script>

<style scoped>
/* ═══ Root ═══ */
.layout-root {
  height: 100vh; overflow: hidden;
}

/* ═══ Layout ═══ */
.layout { height: 100vh; }

/* ═══ Sidebar ═══ */
.sidebar {
  width: 236px !important;
  position: relative;
}
.sidebar-inner {
  height: 100%; display: flex; flex-direction: column;
  background: #25364a;
  border-right: 1px solid #31465f;
}

/* Logo */
.logo { padding: 24px 20px 18px; }
.logo-link {
  display: flex; align-items: center; gap: 8px;
  text-decoration: none;
}
.logo-icon {
  width: 32px; height: 32px; border-radius: 8px;
  background: #e5e7eb;
  color: #0f172a; font-size: 16px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
}
.logo-mark {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  fill: none;
  stroke: #8fb1d8;
  stroke-width: 2;
  stroke-linejoin: round;
}
.logo-copy { display: flex; flex-direction: column; line-height: 1.15; }
.logo-text { font-size: 17px; font-weight: 700; color: #f8fafc; letter-spacing: 0; }
.logo-subtitle { font-size: 11px; color: #94a3b8; margin-top: 2px; }

/* Menu */
.menu { flex: 1; border-right: none !important; padding: 8px 0; position: relative; background: transparent; }
.menu :deep(.el-menu-item) {
  font-size: 13px; color: #cbd5e1;
  margin: 3px 10px; border-radius: 4px; padding: 0 16px !important; height: 40px;
  transition: all 0.2s; display: flex; align-items: center; gap: 8px;
  position: relative; overflow: visible;
}
.menu :deep(.el-menu-item):hover {
  background: rgba(255,255,255,0.08); color: #ffffff;
}
.menu :deep(.el-menu-item.is-active) {
  background: #e8eff7 !important;
  color: #243b53 !important;
  font-weight: 600;
  box-shadow: none;
}
/* Active glow bar */
.menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute; left: -6px; top: 50%; transform: translateY(-50%);
  width: 3px; height: 20px;
  border-radius: 0 3px 3px 0;
  background: #8fb1d8;
}
.menu-icon { display: flex; align-items: center; opacity: 0.55; flex-shrink: 0; transition: all 0.3s; }
.menu :deep(.el-menu-item.is-active) .menu-icon { opacity: 1; }
.menu :deep(.el-menu-item):hover .menu-icon { opacity: 0.85; }
.menu-label { flex: 1; }

/* Footer */
.sidebar-footer { padding: 14px 16px; border-top: 1px solid rgba(255,255,255,0.08); }
.user-row { display: flex; align-items: center; gap: 10px; }
.user-avatar {
  width: 34px; height: 34px; border-radius: 8px;
  background: rgba(255,255,255,0.1); color: #e5e7eb;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 600;
}
.user-meta { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.user-name { font-size: 13px; color: #f8fafc; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: #909399; }
.status-dot {
  width: 7px; height: 7px; border-radius: 50%; background: #67c23a;
  flex-shrink: 0;
}

/* ═══ Right Area ═══ */
.right-area { flex-direction: column; min-width: 0; }

/* Topbar */
.topbar {
  background: #fbfcfe;
  border-bottom: 1px solid #d4dde8;
  display: flex; align-items: center; justify-content: space-between;
  height: 58px; padding: 0 28px;
  position: sticky; top: 0; z-index: 10; flex-shrink: 0;
}
.topbar-left { display: flex; align-items: center; }
.topbar-path { font-size: 15px; color: #111827; font-weight: 700; }
.topbar-actions { display: flex; align-items: center; gap: 8px; }
.action-btn {
  display: flex; align-items: center; gap: 5px;
  color: #606266; font-size: 12px; text-decoration: none;
  padding: 6px 12px; border-radius: 6px;
  border: 1px solid #e4e7ed; transition: all 0.2s;
}
.action-btn:hover { color: #426fa6; border-color: #426fa6; background: #eef3f8; }
.theme-toggle {
  display: flex; align-items: center; padding: 6px 10px;
  background: none; border: 1px solid transparent; border-radius: 6px;
  color: #909399; cursor: pointer; transition: all 0.2s;
}
.theme-toggle:hover { color: #f59e0b; border-color: #fef3c7; background: #fffbeb; }
.notification-btn :deep(.el-badge__content) {
  border: none;
}
.notification-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.notification-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}
.notification-head button {
  border: none;
  background: transparent;
  color: #426fa6;
  cursor: pointer;
  font-size: 12px;
}
.notification-empty {
  color: #94a3b8;
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.notification-item {
  text-align: left;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.notification-item.unread {
  border-color: #bfdbfe;
  background: #eff6ff;
}
.notification-item strong {
  color: #111827;
  font-size: 13px;
}
.notification-item span {
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}
.logout-btn {
  display: flex; align-items: center; padding: 6px 10px;
  background: none; border: 1px solid transparent; border-radius: 6px;
  color: #909399; cursor: pointer; transition: all 0.2s;
}
.logout-btn:hover { color: #f56c6c; border-color: #fde2e2; background: #fef0f0; }

/* Main */
.main-area {
  padding: 28px;
  overflow-y: auto;
  background: #f3f6fa;
}

.topbar-path {
  font-family: Georgia, 'Times New Roman', serif;
  color: #1f2d3d;
}

.action-btn,
.theme-toggle,
.logout-btn {
  border-radius: 4px;
}

.theme-toggle:hover {
  color: #426fa6;
  border-color: #c8d7e8;
  background: #eef3f8;
}
</style>
