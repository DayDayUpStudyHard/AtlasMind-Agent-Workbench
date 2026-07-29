import { createRouter, createWebHistory } from 'vue-router'
import AdminLayout from '../components/AdminLayout.vue'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue'), meta: { noAuth: true } },
  {
    path: '/',
    component: AdminLayout,
    children: [
      { path: '', name: 'Dashboard', component: () => import('../views/Dashboard.vue') },
      { path: 'articles', name: 'ArticleList', component: () => import('../views/ArticleList.vue') },
      { path: 'articles/create', name: 'ArticleCreate', component: () => import('../views/ArticleEdit.vue') },
      { path: 'articles/:id/edit', name: 'ArticleEdit', component: () => import('../views/ArticleEdit.vue') },
      { path: 'categories', name: 'Categories', component: () => import('../views/CategoryManage.vue') },
      { path: 'comments', name: 'Comments', component: () => import('../views/CommentManage.vue') },
      { path: 'tags', name: 'Tags', component: () => import('../views/TagManage.vue') },
      { path: 'moments', name: 'Moments', component: () => import('../views/MomentManage.vue') },
      { path: 'knowledge', name: 'KnowledgeBase', component: () => import('../views/KnowledgeBase.vue') },
      { path: 'ai-observability', name: 'AiObservability', component: () => import('../views/AiObservability.vue') },
      { path: 'about-page', name: 'AboutEdit', component: () => import('../views/AboutEdit.vue') },
      { path: 'logs', name: 'Logs', component: () => import('../views/LogView.vue') },
      { path: 'settings', name: 'Settings', component: () => import('../views/Settings.vue') }
    ]
  }
]

const router = createRouter({
  // 使用 Vite 的 BASE_URL，开发时为 /，生产构建时为 /admin/
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
