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
        path: 'groups/:id',
        name: 'GroupDetail',
        component: () => import('../views/GroupDetailView.vue'),
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
      {
        path: 'api-keys',
        name: 'ApiKeys',
        component: () => import('../views/ApiKeysView.vue'),
      },
      {
        path: 'maintenance',
        name: 'Maintenance',
        component: () => import('../views/MaintenanceView.vue'),
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('../views/AuditView.vue'),
      },
      {
        path: 'incident-groups',
        redirect: '/incidents',
      },
      {
        path: 'probes/:id/timeline',
        name: 'ProbeTimeline',
        component: () => import('../views/ProbeTimelineView.vue'),
      },
      {
        path: 'incidents',
        name: 'Incidents',
        component: () => import('../views/IncidentsView.vue'),
      },
      {
        path: 'templates',
        name: 'Templates',
        component: () => import('../views/TemplatesView.vue'),
      },
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('../views/AdminView.vue'),
        meta: { requiresAdmin: true },
      },
    ],
  },
  {
    path: '/oidc-callback',
    name: 'OidcCallback',
    component: () => import('../views/OidcCallbackView.vue'),
    meta: { public: true },
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
  if (to.meta.requiresAdmin && !auth.isSuperadmin) {
    return { name: 'Dashboard' }
  }
})

export default router
