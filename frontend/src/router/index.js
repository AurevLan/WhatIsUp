import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../views/layouts/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue'),
      },
      {
        path: 'monitors',
        name: 'Monitors',
        component: () => import('../views/MonitorsView.vue'),
      },
      {
        path: 'monitors/:id',
        name: 'MonitorDetail',
        component: () => import('../views/MonitorDetailView.vue'),
      },
      {
        path: 'groups',
        name: 'Groups',
        component: () => import('../views/GroupsView.vue'),
      },
      {
        path: 'probes',
        name: 'Probes',
        component: () => import('../views/ProbesView.vue'),
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('../views/AlertsView.vue'),
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('../views/SettingsView.vue'),
      },
    ],
  },
  {
    path: '/status/:slug',
    name: 'PublicPage',
    component: () => import('../views/PublicPageView.vue'),
    meta: { public: true },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Auth guard
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
})

export default router
