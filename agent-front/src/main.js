import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import naive from 'naive-ui'

window.addEventListener('vite:preloadError', () => {
  const key = 'atlasmind-front-reloaded-after-chunk-error'
  if (sessionStorage.getItem(key) === '1') return
  sessionStorage.setItem(key, '1')
  window.location.reload()
})

const app = createApp(App)
app.use(router)
app.use(naive)
app.mount('#app')
