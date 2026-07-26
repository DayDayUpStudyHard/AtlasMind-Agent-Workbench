import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, getUserInfo } from '../api/index.js'

/**
 * 用户状态管理 — 集中管理认证 token、用户信息、登录/登出。
 * 替代之前分散在 localStorage 和各组件中的状态。
 */
export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('atlasmind-token') || '')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const displayName = computed(() => user.value?.nickname || user.value?.username || '')
  const avatarLetter = computed(() => (displayName.value || 'U').charAt(0).toUpperCase())

  /** 登录：调用 API，存储 token 和用户信息 */
  async function login(username, password) {
    const res = await loginApi({ username, password })
    token.value = res.data.data.token
    user.value = res.data.data.user
    localStorage.setItem('atlasmind-token', token.value)
  }

  /** 获取当前用户信息（已登录后调用） */
  async function fetchUserInfo() {
    try {
      const res = await getUserInfo()
      user.value = res.data.data
    } catch {
      // 401 由 axios 拦截器处理
    }
  }

  /** 登出：清除 token 和用户信息 */
  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('atlasmind-token')
  }

  return { token, user, isLoggedIn, displayName, avatarLetter, login, fetchUserInfo, logout }
})
