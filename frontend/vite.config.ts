import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Route-level code-splitting handles the pages (App.tsx React.lazy). Pull the
    // big shared vendors into their own long-cached chunks so the entry stays small
    // and page chunks don't each re-bundle React/markdown/math. Groups are matched
    // loosely so an absent optional dep (katex/marked) simply yields no chunk.
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (/[\\/]node_modules[\\/](react|react-dom|react-router|react-router-dom|scheduler)[\\/]/.test(id))
            return 'react-vendor'
          if (/[\\/]node_modules[\\/](katex|react-katex)[\\/]/.test(id)) return 'katex'
          if (/[\\/]node_modules[\\/](marked|markdown|dompurify|remark|micromark)/.test(id))
            return 'markdown'
          if (/[\\/]node_modules[\\/]lucide-react[\\/]/.test(id)) return 'icons'
          return 'vendor'
        },
      },
    },
  },
  server: {
    port: 5174,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
