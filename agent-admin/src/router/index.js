import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../components/AdminLayout.vue'
import { getAccessToken, setAccessToken, clearAccessToken, refreshAccessToken } from '../api/index.js'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { noAuth: true } },
  {
    path: '/',
    component: AdminLayout,
    children: [
      { path: '', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'contracts', name: 'ContractManage', component: () => import('../views/ContractManage.vue') },
      { path: 'rules', name: 'ReviewRules', component: () => import('../views/RuleManage.vue') },
      { path: 'clauses', name: 'StandardClauses', component: () => import('../views/ClauseLibrary.vue') },
      { path: 'knowledge', name: 'KnowledgeBase', component: () => import('../views/KnowledgeBase.vue') },
      { path: 'evidence-sync', name: 'EvidenceSync', component: () => import('../views/DocumentParseJobs.vue') },
      { path: 'agent-runs', name: 'AgentRuns', component: () => import('../views/AgentRuns.vue') },
      { path: 'reports', name: 'ReportsApproval', component: () => import('../views/ReportsApproval.vue') },
      { path: 'ai-observability', name: 'AiObservability', component: () => import('../views/AiObservability.vue') },
      { path: 'logs', name: 'Logs', component: () => import('../views/LogView.vue') },
      { path: 'eval', name: 'EvalCenter', component: () => import('../views/EvalCenter.vue') },
      { path: 'users', name: 'Users', component: () => import('../views/Users.vue') },
      { path: 'departments', name: 'Departments', component: () => import('../views/Departments.vue') },
      { path: 'settings', name: 'Settings', component: () => import('../views/Settings.vue') }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach(async (to, from, next) => {
  if (to.meta.noAuth) return next()

  // Already have a token in memory
  if (getAccessToken()) {
    if (to.path === '/login') return next('/')
    return next()
  }

  // No memory token → try silent refresh via httpOnly cookie
  try {
    const token = await refreshAccessToken()
    if (token) {
      setAccessToken(token)
      if (to.path === '/login') return next('/')
      return next()
    }
  } catch {
    clearAccessToken()
  }

  if (to.path !== '/login') return next('/login')
  return next()
})

export default router
