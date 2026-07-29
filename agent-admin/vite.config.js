import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // 生产构建时子路径为 /admin/，开发时保持根路径
  base: mode === 'production' ? '/admin/' : '/',
  plugins: [vue()],
  server: {
    port: 15173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:18080',
        changeOrigin: true,
      },
    },
  },
}))
