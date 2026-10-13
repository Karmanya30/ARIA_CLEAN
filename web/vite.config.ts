import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// the launcher sets ARIA_API_PORT when another app already holds 8000
const API = `http://localhost:${process.env.ARIA_API_PORT || 8000}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API, ws: true }, // ws: the Live Avatar's /api/live/ws
      '/avatar': API,
      '/embed': API,
    },
  },
})
