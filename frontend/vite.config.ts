import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Keep EventSource connection alive (SSE needs this)
        configure: (proxy) => {
          proxy.on("proxyReq", (_proxyReq, _req, res) => {
            res.on("close", () => { _proxyReq.destroy() })
          })
        },
      },
    },
  },
})
