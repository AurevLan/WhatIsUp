import { createApp, defineAsyncComponent } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n/index.js'
import { isNative } from './lib/serverConfig'
import './style.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)

// Global lazy-loaded `<apexchart>` — kept out of the main bundle, and
// MonitorDetailView / SparklineCell rely on global resolution (Vue silently
// renders nothing when the tag is unknown, which is how availability and
// response-time charts once disappeared).
app.component(
  'apexchart',
  defineAsyncComponent(() => import('vue3-apexcharts')),
)

app.mount('#app')

// Register service worker for Web Push — skip on native Capacitor builds
if (!isNative() && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {})
}
