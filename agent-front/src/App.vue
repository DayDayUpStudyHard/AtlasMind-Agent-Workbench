<template>
  <n-config-provider :theme-overrides="themeOverrides" :theme="null">
    <n-message-provider>
    <n-loading-bar-provider>
      <div class="app-root">
        <div class="app-container">
          <AppHeader />
          <main class="main-content">
            <router-view v-slot="{ Component }">
              <transition name="page" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
          </main>
          <AppFooter />
          <ToolsWidget />
          <ChatWindow v-if="route.path !== '/'" />
        </div>
        <button class="theme-toggle" @click="toggleTheme" :title="themeLabel">
          <svg v-if="currentTheme === 'light'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
        </button>
      </div>
    </n-loading-bar-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import AppHeader from './components/AppHeader.vue'
import AppFooter from './components/AppFooter.vue'
import ToolsWidget from './components/ToolsWidget.vue'
import ChatWindow from './components/ChatWindow.vue'
import { useRoute } from 'vue-router'

const currentTheme = ref(localStorage.getItem('atlasmind-theme') || 'light')
const route = useRoute()
const themeLabel = computed(() => currentTheme.value === 'light' ? '切换暗色模式' : '切换亮色模式')

onMounted(() => {
  document.documentElement.setAttribute('data-theme', currentTheme.value)
})

function toggleTheme() {
  currentTheme.value = currentTheme.value === 'light' ? 'dark' : 'light'
  document.documentElement.setAttribute('data-theme', currentTheme.value)
  localStorage.setItem('atlasmind-theme', currentTheme.value)
}

const themeOverrides = {
  common: {
    primaryColor: '#426fa6',
    primaryColorHover: '#315987',
    primaryColorPressed: '#28496f',
    primaryColorSuppl: '#426fa6',
    bodyColor: '#f3f6fa',
    cardColor: '#fbfcfe',
    modalColor: '#fbfcfe',
    popoverColor: '#fbfcfe',
    borderColor: '#d4dde8',
    hoverColor: 'rgba(66,111,166,0.06)',
    fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
    fontFamilyMono: "'JetBrains Mono', 'Fira Code', monospace",
    textColorBase: '#1f2d3d',
    textColor1: '#1f2d3d',
    textColor2: '#607184',
    textColor3: '#8b9aaa',
    inputColor: '#fbfcfe',
    inputColorFocus: '#fbfcfe',
    tagColor: 'rgba(66,111,166,0.08)',
    successColor: '#67c23a',
    successColorHover: '#85ce61',
    warningColor: '#e6a23c',
    errorColor: '#f56c6c',
  },
  Button: {
    textColor: '#426fa6',
    border: '1px solid #426fa6',
    borderHover: '1px solid #315987',
    borderFocus: '1px solid #426fa6',
    borderPressed: '1px solid #28496f',
    colorHover: 'rgba(66,111,166,0.06)',
    colorFocus: 'rgba(66,111,166,0.1)',
    colorPressed: 'rgba(66,111,166,0.14)',
  },
  Input: {
    border: '1px solid #dcdfe6',
    borderHover: '1px solid #c0c4cc',
    borderFocus: '1px solid #426fa6',
    boxShadowFocus: '0 0 0 3px rgba(66,111,166,0.12)',
    placeholderColor: '#c0c4cc',
  },
  Tag: {
    textColor: '#426fa6',
    colorBordered: 'transparent',
    border: '1px solid rgba(66,111,166,0.3)',
  },
  Pagination: {
    itemColor: '#ffffff',
    itemColorActive: '#426fa6',
    itemTextColor: '#606266',
    itemTextColorActive: '#ffffff',
    itemBorder: '1px solid #e4e7ed',
    itemBorderActive: '1px solid #426fa6',
  },
  LoadingBar: { colorLoading: '#426fa6' },
  Spin: { color: '#426fa6' },
}
</script>

<style>
/* ═══ Reset & Base ═══ */
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
  /* Hallmark | macrostructure: Workbench | tone: editorial knowledge desk | anchor hue: ink blue */
  --atlas-bg: #f3f6fa;
  --atlas-surface: #fbfcfe;
  --atlas-surface-soft: #eaf0f7;
  --atlas-border: #d4dde8;
  --atlas-border-strong: #bdcad8;
  --atlas-text: #1f2d3d;
  --atlas-muted: #607184;
  --atlas-subtle: #8b9aaa;
  --atlas-primary: #426fa6;
  --atlas-primary-dark: #315987;
  --atlas-accent: #5e7895;
  --atlas-warning: #a7793d;
  --atlas-radius: 4px;
  --atlas-shadow: 0 1px 2px rgba(31, 45, 61, 0.04), 0 8px 22px rgba(31, 45, 61, 0.05);
  --atlas-font-display: Georgia, 'Times New Roman', serif;
  --atlas-font-body: Inter, system-ui, -apple-system, sans-serif;
}

body {
  background: var(--atlas-bg);
  color: var(--atlas-text);
  font-family: var(--atlas-font-body);
  -webkit-font-smoothing: antialiased;
  overflow-x: clip;
}

::selection { background: rgba(37,99,235,0.18); color: var(--atlas-text); }

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d0d5dd; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #b0b8c4; }

/* ═══ App Shell ═══ */
.app-root { min-height: 100vh; position: relative; }
.app-container {
  min-height: 100vh; display: flex; flex-direction: column;
  position: relative; z-index: 1;
}

/* ═══ Main Content ═══ */
.main-content {
  flex: 1; max-width: 1120px; width: 100%; margin: 0 auto; padding: 32px 24px 48px;
}

/* ═══ Page Transitions ═══ */
.page-enter-active { transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.page-leave-active { transition: all 0.15s ease; }
.page-enter-from { opacity: 0; transform: translateY(16px) scale(0.98); }
.page-leave-to { opacity: 0; transform: translateY(-8px); }

/* ═══ Utility Classes ═══ */
.glass-card {
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: var(--atlas-radius);
  box-shadow: var(--atlas-shadow);
}

/* ═══ Markdown Content ═══ */
.markdown-body { color: #334155; line-height: 1.85; font-size: 16px; }
.markdown-body h1 { font-size: 2em; margin: 0.67em 0; color: #0f172a; font-weight: 700; }
.markdown-body h2 {
  font-size: 1.5em; margin: 1.3em 0 0.6em; color: #0f172a;
  font-weight: 600;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--atlas-border);
}
.markdown-body h3 { font-size: 1.17em; margin: 1em 0 0.5em; color: #0f172a; }
.markdown-body p { margin-bottom: 0.9em; }
.markdown-body a {
  color: var(--atlas-primary); text-decoration: none; border-bottom: 1px solid rgba(37,99,235,0.25);
  transition: all 0.2s;
}
.markdown-body a:hover { color: var(--atlas-primary-dark); }
.markdown-body strong { color: #0f172a; font-weight: 600; }
.markdown-body code {
  background: #eef2ff; color: #315987; padding: 3px 8px; border-radius: 4px;
  font-family: 'JetBrains Mono', monospace; font-size: 0.88em; border: 1px solid #dbeafe;
}
.markdown-body pre {
  background: #0f172a; border: 1px solid #111827; border-radius: 8px;
  padding: 20px; overflow-x: auto; margin: 16px 0;
}
.markdown-body pre code { background: none; border: none; padding: 0; color: #e5e7eb; font-size: 14px; line-height: 1.6; }
.markdown-body blockquote {
  border-left: 3px solid var(--atlas-primary);
  padding: 12px 20px; margin: 16px 0;
  background: #f8fafc;
  border-radius: 0 8px 8px 0; color: #475569;
}
.markdown-body ul, .markdown-body ol { padding-left: 1.5em; margin-bottom: 0.9em; }
.markdown-body li { margin-bottom: 0.3em; }
.markdown-body img { max-width: 100%; border-radius: 8px; border: 1px solid var(--atlas-border); }
.markdown-body hr { border: none; height: 1px; background: var(--atlas-border); margin: 2em 0; }
.markdown-body table { width: 100%; border-collapse: collapse; margin: 16px 0; }
.markdown-body th { background: #f8fafc; padding: 10px 16px; text-align: left; color: #0f172a; border: 1px solid var(--atlas-border); }
.markdown-body td { padding: 8px 16px; border: 1px solid var(--atlas-border); }

/* ═══ Theme Toggle ═══ */
.theme-toggle {
  position: fixed; bottom: 32px; left: 32px; z-index: 100;
  width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid rgba(0,0,0,0.08);
  background: rgba(255,255,255,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  color: #909399; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06), 0 4px 16px rgba(0,0,0,0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.theme-toggle:hover {
  transform: translateY(-2px);
  color: #f59e0b;
  box-shadow: 0 4px 12px rgba(245,158,11,0.15), 0 8px 24px rgba(0,0,0,0.08);
}

/* ═══ Dark Mode ═══ */
[data-theme="dark"] body {
  --atlas-bg: #152235;
  --atlas-surface: #1d2d42;
  --atlas-surface-soft: #243953;
  --atlas-border: rgba(218, 229, 241, 0.14);
  --atlas-border-strong: rgba(218, 229, 241, 0.24);
  --atlas-text: #e7eef7;
  --atlas-muted: #a9b9ca;
  --atlas-subtle: #7f93aa;
  --atlas-primary: #8fb1d8;
  --atlas-primary-dark: #b0c9e5;
  --atlas-accent: #9eb7d2;
  background: var(--atlas-bg);
}

[data-theme="dark"] .glass-card {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
}

/* Header */
[data-theme="dark"] .app-header {
  background: rgba(15, 23, 42, 0.8) !important;
  border-bottom-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .header-links a { color: #94a3b8 !important; }
[data-theme="dark"] .header-links a:hover { color: #60a5fa !important; }
[data-theme="dark"] .header-links a.router-link-exact-active { color: #60a5fa !important; }

/* Cards */
[data-theme="dark"] .card-inner.hover {
  background: rgba(30, 41, 59, 0.75) !important;
  border-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .title { color: #e2e8f0 !important; }
[data-theme="dark"] .card-inner.hover .title {
  background: none;
  color: #e2e8f0 !important;
  -webkit-text-fill-color: currentColor;
}
[data-theme="dark"] .summary { color: #94a3b8 !important; }
[data-theme="dark"] .meta { color: #64748b !important; }
[data-theme="dark"] .card:not(:last-child)::after {
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.06) 20%, rgba(255,255,255,0.06) 80%, transparent) !important;
}

/* Hero */
[data-theme="dark"] .hero-subtitle { color: #94a3b8 !important; }
[data-theme="dark"] .featured-card {
  background: rgba(30, 41, 59, 0.8) !important;
  border-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .featured-title { color: #e2e8f0 !important; }
[data-theme="dark"] .featured-summary { color: #94a3b8 !important; }
[data-theme="dark"] .featured-cover.placeholder {
  background: var(--atlas-surface-soft) !important;
}

[data-theme="dark"] .meta-sep { color: #475569 !important; }
[data-theme="dark"] .nav-link {
  background: rgba(30, 41, 59, 0.6) !important;
  border-color: rgba(255,255,255,0.06) !important;
}
[data-theme="dark"] .nav-link:hover { background: rgba(30, 41, 59, 0.85) !important; }
[data-theme="dark"] .nav-title { color: #e2e8f0 !important; }

/* Markdown content in dark mode */
[data-theme="dark"] .markdown-body { color: #cbd5e1 !important; }
[data-theme="dark"] .markdown-body h1 { color: #e2e8f0 !important; }
[data-theme="dark"] .markdown-body h3 { color: #e2e8f0 !important; }
[data-theme="dark"] .markdown-body strong { color: #e2e8f0 !important; }
[data-theme="dark"] .markdown-body code {
  background: rgba(30,41,59,0.6) !important; color: #60a5fa !important;
  border-color: rgba(255,255,255,0.08) !important;
}
[data-theme="dark"] .markdown-body pre {
  background: rgba(30,41,59,0.5) !important;
  border-color: rgba(255,255,255,0.08) !important;
}
[data-theme="dark"] .markdown-body pre code { color: #cbd5e1 !important; }
[data-theme="dark"] .markdown-body blockquote {
  background: rgba(30,41,59,0.5) !important;
  color: #94a3b8 !important;
}
[data-theme="dark"] .markdown-body th { background: rgba(30,41,59,0.6) !important; border-color: rgba(255,255,255,0.08) !important; }
[data-theme="dark"] .markdown-body td { border-color: rgba(255,255,255,0.08) !important; }

/* Theme toggle dark */
[data-theme="dark"] .theme-toggle {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
  color: var(--atlas-muted);
}
[data-theme="dark"] .theme-toggle:hover { color: #fbbf24; }

/* BackToTop */
[data-theme="dark"] .back-to-top {
  background: rgba(30, 41, 59, 0.8);
}
[data-theme="dark"] .ring-bg { stroke: rgba(255,255,255,0.1); }

/* Footer */
[data-theme="dark"] .app-footer { color: #64748b !important; border-top-color: rgba(255,255,255,0.06) !important; }

/* Pagination */
[data-theme="dark"] .n-pagination .n-pagination-item {
  background: rgba(30,41,59,0.6) !important;
  color: #94a3b8 !important;
  border-color: rgba(255,255,255,0.08) !important;
}
[data-theme="dark"] .n-pagination .n-pagination-item--active {
  background: #426fa6 !important; color: #fff !important;
}

/* Empty state */
[data-theme="dark"] .n-empty .n-empty__description { color: #64748b !important; }

/* Search box in header */
[data-theme="dark"] .search-box { background: rgba(255,255,255,0.06); }
[data-theme="dark"] .search-box:focus-within { background: rgba(30,41,59,0.9); }
[data-theme="dark"] .search-input { color: #e2e8f0; }
[data-theme="dark"] .search-input::placeholder { color: #64748b; }
[data-theme="dark"] .search-hint { color: #94a3b8; }

@media (max-width: 760px) {
  .main-content {
    padding: 20px 16px 40px;
  }
  .theme-toggle {
    left: 16px;
    bottom: 18px;
  }
}

/* Hallmark | light-theme overrides: paper surfaces, ink-blue accents, no decorative gradients */
body,
[data-theme="dark"] body {
  background-image: none !important;
}

.glass-card {
  border-radius: 4px;
  box-shadow: none;
}

.theme-toggle {
  border-radius: 4px;
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
  box-shadow: none;
}

.theme-toggle:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
  box-shadow: none;
}
</style>
