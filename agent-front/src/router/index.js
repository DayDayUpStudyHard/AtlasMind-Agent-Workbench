import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/ProjectOverviewView.vue') },
  { path: '/projects/:id', name: 'ProjectWorkbench', component: () => import('../views/ProjectWorkbenchView.vue') },
  { path: '/article/:id', name: 'ArticleDetail', component: () => import('../views/ArticleDetail.vue') },
  { path: '/categories', name: 'Categories', component: () => import('../views/CategoryView.vue') },
  { path: '/knowledge', name: 'Knowledge', component: () => import('../views/KnowledgeView.vue') },
  { path: '/archive', name: 'Archive', component: () => import('../views/ArchiveView.vue') },
  { path: '/moments', name: 'Moments', component: () => import('../views/MomentView.vue') },
  { path: '/guestbook', name: 'Guestbook', component: () => import('../views/GuestbookView.vue') },
  { path: '/about', name: 'About', component: () => import('../views/AboutView.vue') }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router

