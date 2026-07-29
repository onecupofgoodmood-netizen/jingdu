import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/775069-proxy': {
        target: 'http://775069.xyz',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/775069-proxy/, ''),
      },
    },
  },
})
