import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/HomeAiView.vue') },
  { path: '/article/:id', name: 'ArticleDetail', component: () => import('../views/ArticleDetail.vue') },
  { path: '/categories', name: 'Categories', component: () => import('../views/CategoryView.vue') },
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
