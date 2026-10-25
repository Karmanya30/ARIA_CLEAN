import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// the launcher sets ARIA_API_PORT when another app already holds 8000
const API = `http://localhost:${process.env.ARIA_API_PORT || 8000}`
// the local talking-avatar engine (avatar_engine/) listens here
const AVATAR_ENGINE = `http://localhost:${process.env.ARIA_AVATAR_PORT || 8010}`

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // first, because '/avatar' below also matches by prefix: /avatar-engine/health -> engine /health, ws for /stream
      '/avatar-engine': { target: AVATAR_ENGINE, ws: true, rewrite: (p) => p.replace(/^\/avatar-engine/, '') },
      '/api': { target: API, ws: true }, // ws: the Live Avatar's /api/live/ws
      '/avatar': API,
      '/embed': API,
    },
  },
})
