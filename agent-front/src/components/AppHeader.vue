<template>
  <header class="header" :class="{ scrolled }">
    <div class="header-inner">
      <router-link to="/" class="logo">
        <svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true">
          <path d="M4 4h16v16H4z" />
          <path d="M8 8h16v16H8z" />
        </svg>
        <span class="logo-text">AtlasMind</span>
      </router-link>
      <nav class="nav">
        <router-link to="/" class="nav-link">
          <span class="nav-label">工作台</span>
        </router-link>
        <router-link to="/knowledge" class="nav-link">
          <span class="nav-label">知识来源</span>
        </router-link>
      </nav>
      <div class="search-box" @submit.prevent="doSearch">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input
          v-model="keyword"
          type="text"
          class="search-input"
          placeholder="搜索项目或证据..."
          @keyup.enter="doSearch"
        />
      </div>
      <div class="header-actions">
        <a class="admin-link" :href="adminUrl" target="_blank" rel="noreferrer">管理端</a>
        <button type="button" class="logout-button" @click="logout">退出</button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const keyword = ref('')
const scrolled = ref(false)
const adminUrl = import.meta.env.VITE_ADMIN_URL || 'http://localhost:15173/'

if (typeof window !== 'undefined') {
  window.addEventListener('scroll', () => { scrolled.value = window.scrollY > 10 })
}

function doSearch() {
  const q = keyword.value.trim()
  if (q) {
    router.push({ path: '/', query: { keyword: q } })
  } else {
    router.push({ path: '/' })
  }
}

function logout() {
  localStorage.removeItem('atlasmind-token')
  router.push('/login')
}
</script>

<style scoped>
.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(247,248,251,0.88);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--atlas-border);
  transition: box-shadow 0.25s, background 0.25s;
}
.header.scrolled {
  background: rgba(255,255,255,0.94);
  box-shadow: 0 8px 24px rgba(15,23,42,0.06);
}
.header-inner {
  max-width: 1120px; margin: 0 auto; padding: 0 24px;
  display: flex; justify-content: space-between; align-items: center; height: 60px;
  gap: 24px;
  box-sizing: border-box;
}

/* Logo */
.logo {
  display: flex; align-items: center; gap: 8px;
  text-decoration: none;
}
.logo-mark {
  width: 30px; height: 30px; flex: 0 0 auto;
  fill: none; stroke: var(--atlas-primary); stroke-width: 2;
  stroke-linejoin: round;
}
.logo-text {
  color: var(--atlas-text);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 19px;
  font-weight: 700;
}

/* Nav */
.nav { display: flex; gap: 2px; flex: 1; min-width: 0; justify-content: center; }
.nav-link {
  padding: 7px 12px; border-radius: 6px; text-decoration: none;
  font-size: 14px; color: var(--atlas-muted); transition: all 0.15s;
}
.nav-link:hover {
  background: var(--atlas-surface-soft); color: var(--atlas-text);
}
.nav-link.router-link-active {
  color: var(--atlas-primary);
  font-weight: 700;
  box-shadow: inset 0 -2px 0 var(--atlas-primary);
}

/* Search Box */
.search-box {
  display: flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 10px; border-radius: 4px;
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  transition: border-color 0.2s, box-shadow 0.2s;
  min-width: 0;
}
.search-box:focus-within {
  border-color: var(--atlas-primary);
  box-shadow: 0 0 0 3px rgba(66,111,166,0.12);
}
.search-icon {
  color: #c0c4cc; flex-shrink: 0;
  transition: color 0.2s;
}
.search-box:focus-within .search-icon { color: var(--atlas-primary); }
.search-input {
  border: none; outline: none; background: transparent;
  font-size: 13px; color: var(--atlas-text); width: 130px;
  font-family: inherit;
}
.search-input::placeholder { color: #c0c4cc; }

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.admin-link,
.logout-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 10px;
  color: var(--atlas-muted);
  background: var(--atlas-surface);
  border: 1px solid var(--atlas-border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
  text-decoration: none;
  white-space: nowrap;
}

.admin-link:hover,
.logout-button:hover {
  color: var(--atlas-primary);
  border-color: var(--atlas-primary);
}

@media (max-width: 860px) {
  .header-inner {
    height: auto;
    min-height: 60px;
    flex-wrap: wrap;
    gap: 10px;
    padding: 12px 16px;
  }
  .nav {
    order: 3;
    flex: 0 0 100%;
    width: 100%;
    min-width: 0;
    overflow-x: auto;
    justify-content: flex-start;
    padding-bottom: 2px;
  }
  .nav-link {
    white-space: nowrap;
  }
  .search-box {
    margin-left: auto;
    max-width: min(172px, calc(100vw - 190px));
  }

  .search-input {
    width: 100%;
    min-width: 0;
  }
}

@media (max-width: 420px) {
  .header-inner {
    align-items: flex-start;
  }

  .logo {
    min-height: 34px;
  }

  .search-box {
    order: 2;
    flex: 1 1 calc(100% - 96px);
    width: auto;
    max-width: none;
    margin-left: 0;
  }

  .header-actions {
    order: 2;
    margin-left: auto;
  }

  .nav {
    order: 3;
  }
}

[data-theme="dark"] .header {
  background: rgba(11,17,32,0.88);
  border-bottom-color: var(--atlas-border);
}
[data-theme="dark"] .header.scrolled {
  background: rgba(17,24,39,0.94);
}
[data-theme="dark"] .logo-mark { stroke: #8fb1d8; }
[data-theme="dark"] .nav-link.router-link-active { color: #8fb1d8; }
[data-theme="dark"] .search-box {
  background: var(--atlas-surface);
  border-color: var(--atlas-border);
}
</style>
