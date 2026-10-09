import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { vehicleBackendPlugin } from './backend/vite-plugin.mjs'
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const target = env.VITE_BACKEND_URL || 'http://127.0.0.1:8787'
  const proxy = { '/api': { target, changeOrigin: true } }
  return { plugins: [react(), tailwindcss(), vehicleBackendPlugin(!env.VITE_BACKEND_URL, env.CXX)], server: { proxy }, preview: { proxy } }
})
