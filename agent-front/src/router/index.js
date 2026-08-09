import { createRouter, createWebHistory } from 'vue-router'
import { getAccessToken, setAccessToken, clearAccessToken, refreshAccessToken } from '../api/index.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: '/', name: 'Home', component: () => import('../views/ContractPortfolioView.vue') },
  { path: '/contracts', name: 'ContractPortfolio', component: () => import('../views/ContractPortfolioView.vue') },
  { path: '/contracts/new', name: 'ContractCreate', component: () => import('../views/ContractCreateView.vue') },
  { path: '/contracts/:id', name: 'ContractCase', component: () => import('../views/ContractCaseView.vue') },
  { path: '/knowledge', name: 'Knowledge', component: () => import('../views/KnowledgeView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, from, next) => {
  // Public pages (login) always allowed
  if (to.meta.public) return next()

  // Already have a token in memory → good to go
  if (getAccessToken()) {
    if (to.path === '/login') return next('/')
    return next()
  }

  // No memory token → try silent refresh via httpOnly cookie
  try {
    const token = await refreshAccessToken()
    if (token) {
      if (to.path === '/login') return next('/')
      return next()
    }
  } catch {
    // Refresh failed
    clearAccessToken()
  }

  // Not authenticated → login page
  if (to.path !== '/login') return next('/login')
  return next()
})

export default router
