import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const gatewayKey = env.GATEWAY_KEY || env.VITE_GATEWAY_KEY || env.VITE_API_KEY || ''

  return {
    plugins: [react()],
    define: {
      'import.meta.env.VITE_GATEWAY_KEY': JSON.stringify(gatewayKey),
    },
    server: {
      host: true, // Listen on all network interfaces
      port: 5173,
      cors: true,
      allowedHosts: true,
      proxy: {
        '/v1': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/healthz': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/admin': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  }
})



