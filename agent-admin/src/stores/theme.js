import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * 主题状态管理 — 集中管理亮/暗主题切换，替代 window.__adminTheme 全局变量。
 */
export const useThemeStore = defineStore('theme', () => {
  const theme = ref(localStorage.getItem('agent-admin-theme') || 'light')

  const isDark = computed(() => theme.value === 'dark')

  /** 应用主题到 document（初始化时调用） */
  function apply() {
    document.documentElement.setAttribute('data-theme', theme.value)
  }

  /** 切换亮暗主题 */
  function toggle() {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
    localStorage.setItem('agent-admin-theme', theme.value)
    apply()
  }

  return { theme, isDark, apply, toggle }
})
