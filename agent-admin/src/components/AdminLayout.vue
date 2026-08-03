<template>
  <div class="layout-root">
    <el-container class="layout">
      <el-aside width="232px" class="sidebar">
        <div class="sidebar-inner">
          <router-link to="/" class="logo-link">
            <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true">
              <path d="M4 4h16v16H4z" />
              <path d="M8 8h16v16H8z" />
            </svg>
            <span class="logo-copy">
              <span class="logo-text">AtlasMind</span>
              <span class="logo-subtitle">Agent Operations</span>
            </span>
          </router-link>

          <el-menu :default-active="activePath" router class="menu">
            <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
              <template #title>
                <span class="menu-icon" v-html="item.icon"></span>
                <span class="menu-label">{{ item.label }}</span>
              </template>
            </el-menu-item>
          </el-menu>

          <div class="sidebar-footer">
            <div class="ops-card">
              <span>Deployment</span>
              <strong>Single Team</strong>
              <small>Local workspace mode</small>
            </div>
            <div class="user-row">
              <div class="user-avatar">
                <span>{{ userStore.avatarLetter }}</span>
              </div>
              <div class="user-meta">
                <span class="user-name">{{ userStore.displayName || 'Admin' }}</span>
                <span class="user-role">Workspace admin</span>
              </div>
              <div class="status-dot" title="Online"></div>
            </div>
          </div>
        </div>
      </el-aside>

      <el-container class="right-area">
        <el-header class="topbar">
          <div class="topbar-left">
            <span class="topbar-path">{{ pageTitle }}</span>
            <span class="topbar-subtitle">Platform operations, evidence, Agent runs, and audit state</span>
          </div>
          <div class="topbar-actions">
            <el-popover placement="bottom-end" width="320" trigger="click" @show="fetchNotifications">
              <template #reference>
                <button class="icon-button notification-btn" title="Notifications">
                  <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7" />
                      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                    </svg>
                  </el-badge>
                </button>
              </template>
              <div class="notification-panel">
                <div class="notification-head">
                  <strong>通知中心</strong>
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
            <button class="icon-button" @click="themeStore.toggle" :title="themeStore.isDark ? '切换亮色模式' : '切换暗色模式'">
              <svg v-if="!themeStore.isDark" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
              <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="5" />
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </svg>
            </button>
            <a :href="portalFrontUrl" target="_blank" class="action-btn" title="打开合同工作台">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <path d="M15 3h6v6" />
                <path d="M10 14 21 3" />
              </svg>
              <span>合同工作台</span>
            </a>
            <button class="icon-button logout-btn" @click="logout" title="退出登录">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <path d="M16 17l5-5-5-5" />
                <path d="M21 12H9" />
              </svg>
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

const icons = {
  console: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3"/></svg>',
  project: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 7h7l2 2h9v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2"/></svg>',
  knowledge: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/><path d="M8 7h8M8 11h6"/></svg>',
  sync: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21 12a9 9 0 0 1-15.5 6.2"/><path d="M3 12A9 9 0 0 1 18.5 5.8"/><path d="M7 18H5v2"/><path d="M17 6h2V4"/></svg>',
  run: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 4v16"/><path d="M19 12 8 5v14z"/></svg>',
  report: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/></svg>',
  observe: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 3v18h18"/><path d="M7 15l3-3 3 2 5-7"/></svg>',
  log: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 4h16v16H4z"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  settings: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4z"/></svg>'
}

const menuItems = [
  { path: '/', label: '合同驾驶舱', icon: icons.console },
  { path: '/rules', label: '审查规则管理', icon: icons.project },
  { path: '/clauses', label: '标准条款库', icon: icons.knowledge },
  { path: '/knowledge', label: '知识来源', icon: icons.sync },
  { path: '/agent-runs', label: 'Agent 运行记录', icon: icons.run },
  { path: '/reports', label: '报告与审批', icon: icons.report },
  { path: '/ai-observability', label: '可观测性', icon: icons.observe },
  { path: '/logs', label: '系统日志', icon: icons.log },
  { path: '/settings', label: '系统设置', icon: icons.settings }
]

const titleMap = Object.fromEntries(menuItems.map(item => [item.path, item.label]))
const activePath = computed(() => {
  const exact = menuItems.find(item => item.path === route.path)
  if (exact) return exact.path
  return menuItems.find(item => item.path !== '/' && route.path.startsWith(item.path))?.path || '/'
})
const pageTitle = computed(() => titleMap[activePath.value] || 'Agent 控制台')

onMounted(async () => {
  try {
    await userStore.fetchUserInfo()
    await fetchUnreadCount()
    notificationTimer = window.setInterval(fetchUnreadCount, 8000)
  } catch {
    userStore.logout()
    router.push('/login')
  }
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
.layout-root {
  height: 100vh;
  overflow: hidden;
}

.layout {
  height: 100vh;
}

.sidebar {
  background: #203247;
  color: #d8e2ee;
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.logo-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 22px 18px 18px;
  color: inherit;
  text-decoration: none;
}

.logo-mark {
  width: 30px;
  height: 30px;
  fill: none;
  stroke: #9bb8da;
  stroke-width: 2;
  stroke-linejoin: round;
}

.logo-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.logo-text {
  color: #ffffff;
  font-size: 18px;
  font-weight: 800;
}

.logo-subtitle {
  color: #8ca3ba;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 10px;
}

:deep(.el-menu-item) {
  height: 42px;
  margin: 3px 0;
  padding: 0 12px !important;
  border-radius: 4px;
  color: #b7c5d6;
}

:deep(.el-menu-item:hover),
:deep(.el-menu-item.is-active) {
  background: #e8eef6;
  color: #1f2d3d;
}

.menu-icon {
  display: inline-flex;
  width: 18px;
  margin-right: 10px;
}

.menu-label {
  font-size: 14px;
  font-weight: 700;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.ops-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  margin-bottom: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
}

.ops-card span,
.ops-card small {
  color: #8ca3ba;
  font-size: 11px;
}

.ops-card strong {
  color: #ffffff;
  font-size: 13px;
}

.user-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 4px;
  background: #426fa6;
  color: #ffffff;
  font-weight: 800;
}

.user-meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.user-name {
  color: #ffffff;
  font-size: 13px;
  font-weight: 800;
}

.user-role {
  color: #8ca3ba;
  font-size: 11px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

.right-area {
  min-width: 0;
  background: #f3f6fa;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 22px;
  background: #fbfcfe;
  border-bottom: 1px solid #dce4ee;
}

.topbar-left {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.topbar-path {
  color: #1f2d3d;
  font-size: 16px;
  font-weight: 800;
}

.topbar-subtitle {
  color: #8b9aaa;
  font-size: 12px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.icon-button,
.action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 34px;
  border: 1px solid #d4dde8;
  border-radius: 4px;
  background: #ffffff;
  color: #607184;
  cursor: pointer;
  text-decoration: none;
}

.icon-button {
  width: 34px;
}

.action-btn {
  gap: 7px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 700;
}

.icon-button:hover,
.action-btn:hover {
  color: #426fa6;
  border-color: #426fa6;
}

.main-area {
  height: calc(100vh - 64px);
  overflow: auto;
  padding: 22px;
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
  margin-bottom: 4px;
}

.notification-head button {
  border: 0;
  background: transparent;
  color: #426fa6;
  cursor: pointer;
}

.notification-empty {
  padding: 18px 0;
  color: #8b9aaa;
  text-align: center;
}

.notification-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  padding: 10px;
  border: 1px solid #dce4ee;
  border-radius: 4px;
  background: #ffffff;
  color: #607184;
  text-align: left;
  cursor: pointer;
}

.notification-item.unread {
  border-color: #426fa6;
  background: #eef3f8;
}

.notification-item strong {
  color: #1f2d3d;
}

.notification-item span {
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 860px) {
  .sidebar {
    display: none;
  }

  .topbar {
    align-items: flex-start;
    height: auto;
    min-height: 64px;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
  }

  .topbar-actions {
    flex-wrap: wrap;
  }

  .main-area {
    height: calc(100vh - 112px);
    padding: 16px;
  }
}
</style>
