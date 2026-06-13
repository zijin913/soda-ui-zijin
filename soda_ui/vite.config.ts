import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // Emit the SPA bundle under /spa/ instead of the default /assets/. When the
  // backend serves this build single-origin (production / Docker), /assets is
  // already taken by the URDF mesh mount — keeping them separate avoids a 404.
  build: {
    assetsDir: 'spa',
  },
  plugins: [
    vue(),
    vueDevTools(),
    tailwindcss()
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
})
