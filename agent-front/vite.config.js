import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 15174,
    strictPort: true,
    proxy: {
      '/api/chat/': {
        target: 'http://localhost:18088',
        changeOrigin: true,
      },
    },
  },
})
