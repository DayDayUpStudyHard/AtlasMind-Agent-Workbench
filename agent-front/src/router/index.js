import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: '/', name: 'Home', component: () => import('../views/ProjectOverviewView.vue') },
  { path: '/projects/:id', name: 'ProjectWorkbench', component: () => import('../views/ProjectWorkbenchView.vue') },
  { path: '/contracts', name: 'ContractPortfolio', component: () => import('../views/ContractPortfolioView.vue') },
  { path: '/contracts/new', name: 'ContractCreate', component: () => import('../views/ContractCaseView.vue') },
  { path: '/contracts/:id', name: 'ContractCase', component: () => import('../views/ContractCaseView.vue') },
  { path: '/knowledge', name: 'Knowledge', component: () => import('../views/KnowledgeView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('atlasmind-token')
  if (!to.meta.public && !token) {
    next('/login')
  } else if (to.path === '/login' && token) {
    next('/')
  } else {
    next()
  }
})

export default router
