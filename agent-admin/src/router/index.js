import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../components/AdminLayout.vue'

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
      { path: 'settings', name: 'Settings', component: () => import('../views/Settings.vue') }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('atlasmind-token')
  if (!to.meta.noAuth && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/')
  } else {
    next()
  }
})

export default router
