<template>
  <div class="admin-app">
    <router-view v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <component :is="Component" />
      </Transition>
    </router-view>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useThemeStore } from './stores/theme.js'

const themeStore = useThemeStore()
onMounted(() => themeStore.apply())
</script>

<style>
.admin-app { min-height: 100vh; position: relative; }

.page-enter-active,
.page-leave-active {
  transition: all 0.25s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(12px) scale(0.98);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ═══ Dark Mode ═══ */
[data-theme="dark"] .admin-app {
  color: #e0e0e0;
}

[data-theme="dark"] body {
  background: #0f172a;
}

/* Sidebar */
[data-theme="dark"] .sidebar-inner {
  background: #0f172a !important;
  border-right-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .logo-text { color: #e2e8f0 !important; }
[data-theme="dark"] .menu .el-menu-item { color: #94a3b8 !important; }
[data-theme="dark"] .menu .el-menu-item:hover { background: rgba(255,255,255,0.08) !important; color: #ffffff !important; }
[data-theme="dark"] .menu .el-menu-item.is-active { background: #e5e7eb !important; color: #0f172a !important; }
[data-theme="dark"] .sidebar-footer { border-top-color: rgba(255,255,255,0.06) !important; }
[data-theme="dark"] .user-name { color: #e2e8f0 !important; }
[data-theme="dark"] .user-role { color: #94a3b8 !important; }

/* Topbar */
[data-theme="dark"] .topbar {
  background: #111827 !important;
  border-bottom-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .topbar-path { color: #e2e8f0 !important; }
[data-theme="dark"] .action-btn { color: #94a3b8 !important; border-color: rgba(255,255,255,0.1) !important; }
[data-theme="dark"] .action-btn:hover { color: #60a5fa !important; border-color: #60a5fa !important; background: rgba(64,158,255,0.1) !important; }
[data-theme="dark"] .logout-btn:hover { background: rgba(245,108,108,0.1) !important; border-color: rgba(245,108,108,0.2) !important; }

/* Main area */
[data-theme="dark"] .main-area { background: #0b1120; }

/* Cards & panels */
[data-theme="dark"] .stat-card {
  background: #111827 !important;
  border-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .num { color: #e2e8f0 !important; }
[data-theme="dark"] .label { color: #94a3b8 !important; }
[data-theme="dark"] .page-title { color: #e2e8f0 !important; }

/* Forms */
[data-theme="dark"] .el-input__inner {
  background: rgba(30,41,59,0.8) !important;
  border-color: rgba(255,255,255,0.1) !important;
  color: #e2e8f0 !important;
}
[data-theme="dark"] .el-input__inner:focus {
  border-color: #426fa6 !important;
}
[data-theme="dark"] .el-input__inner::placeholder { color: #64748b !important; }

/* Table */
[data-theme="dark"] .el-table {
  background: rgba(30,41,59,0.6) !important;
  color: #e2e8f0 !important;
}
[data-theme="dark"] .el-table th {
  background: rgba(30,41,59,0.8) !important;
  color: #94a3b8 !important;
}
[data-theme="dark"] .el-table td { border-bottom-color: rgba(255,255,255,0.05) !important; }
[data-theme="dark"] .el-table tr:hover td { background: rgba(64,158,255,0.05) !important; }

/* Dialog */
[data-theme="dark"] .el-dialog {
  background: #1e293b !important;
  border: 1px solid rgba(255,255,255,0.08);
}
[data-theme="dark"] .el-dialog__title { color: #e2e8f0 !important; }

/* Pagination */
[data-theme="dark"] .el-pagination button,
[data-theme="dark"] .el-pager li {
  background: rgba(30,41,59,0.6) !important;
  color: #94a3b8 !important;
}
[data-theme="dark"] .el-pager li.active { background: #426fa6 !important; color: #fff !important; }

/* Page header */
[data-theme="dark"] .page-header .page-title { color: #e2e8f0 !important; }
</style>
