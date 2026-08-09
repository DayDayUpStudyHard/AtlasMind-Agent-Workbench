import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { login as loginApi, logout as logoutApi, getUserInfo, setAccessToken, clearAccessToken } from '../api/index.js'

/**
 * 用户状态管理 — 集中管理认证 token、用户信息、登录/登出。
 * Token 存储在内存中（通过 api/index.js 的 setAccessToken/getAccessToken），
 * refresh token 通过 httpOnly cookie 自动携带。
 */
export const useUserStore = defineStore('user', () => {
  const token = ref('')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)
  const displayName = computed(() => user.value?.nickname || user.value?.username || '')
  const avatarLetter = computed(() => (displayName.value || 'U').charAt(0).toUpperCase())
  const departmentName = computed(() => user.value?.departmentName || '')
  const roleLabel = computed(() => {
    if (user.value?.role === 'ADMIN') return '管理员'
    if (user.value?.role === 'USER') return '普通用户'
    return ''
  })

  /** 登录：调用 API，存储 token 和用户信息 */
  async function login(username, password) {
    const res = await loginApi({ username, password })
    const t = res.data?.data?.token
    if (t) {
      token.value = t
      setAccessToken(t)
    }
    user.value = res.data?.data?.user || null
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

  /** 登出：清除 token 和用户信息，调用服务端注销 */
  async function logout() {
    try {
      await logoutApi()
    } catch {
      // 即使服务端调用失败也清除本地状态
    }
    token.value = ''
    user.value = null
    clearAccessToken()
  }

  return { token, user, isLoggedIn, displayName, avatarLetter, departmentName, roleLabel, login, fetchUserInfo, logout }
})
