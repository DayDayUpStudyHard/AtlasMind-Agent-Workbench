import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/ProjectOverviewView.vue') },
  { path: '/projects/:id', name: 'ProjectWorkbench', component: () => import('../views/ProjectWorkbenchView.vue') },
  { path: '/knowledge', name: 'Knowledge', component: () => import('../views/KnowledgeView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
