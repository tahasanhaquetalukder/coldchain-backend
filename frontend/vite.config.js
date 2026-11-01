import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // the recharts chunk is ~550 kB minified and cannot shrink without dropping the library the
    // charts are built on, so it is loaded on demand rather than warned about.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // recharts and the d3 behind it are most of the bundle and only the two charts need them,
        // so they ship as a chunk of their own instead of one file over the size limit.
        manualChunks: { charts: ['recharts'] },
      },
    },
  },
})