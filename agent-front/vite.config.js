import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 15174,
    strictPort: true,
    // The development server shares localhost with many short-lived local
    // tools. Never let a browser reuse a stale HTML or asset response from a
    // prior process on this port.
    headers: {
      'Cache-Control': 'no-store, max-age=0, must-revalidate',
      Pragma: 'no-cache',
      Expires: '0',
    },
    proxy: {
      '/api/chat/': {
        target: 'http://127.0.0.1:18088',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:18080',
        changeOrigin: true,
      },
    },
  },
})
