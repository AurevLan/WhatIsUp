import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { isConfigured } from '../lib/serverConfig'
import { i18n } from '../i18n'

const routes = [
  {
    path: '/setup',
    name: 'ServerSetup',
    component: () => import('../views/ServerSetupView.vue'),
    meta: { public: true, setup: true },
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true, titleKey: 'auth.login' },
  },
  {
    path: '/',
    component: () => import('../views/layouts/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue'),
        meta: { titleKey: 'nav.dashboard' },
      },
      {
        path: 'monitors',
        name: 'Monitors',
        component: () => import('../views/MonitorsView.vue'),
        meta: { titleKey: 'nav.monitors' },
      },
      {
        path: 'monitors/:id',
        name: 'MonitorDetail',
        component: () => import('../views/MonitorDetailView.vue'),
        meta: { titleKey: 'nav.monitors' },
      },
      {
        path: 'groups/:id',
        name: 'GroupDetail',
        component: () => import('../views/GroupDetailView.vue'),
        meta: { titleKey: 'nav.groups' },
      },
      {
        path: 'groups',
        name: 'Groups',
        component: () => import('../views/GroupsView.vue'),
        meta: { titleKey: 'nav.groups' },
      },
      {
        path: 'probes',
        name: 'Probes',
        component: () => import('../views/ProbesView.vue'),
        meta: { titleKey: 'nav.probes' },
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('../views/AlertsView.vue'),
        meta: { titleKey: 'nav.alerts' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('../views/SettingsView.vue'),
        meta: { titleKey: 'nav.settings' },
      },
      {
        path: 'api-keys',
        name: 'ApiKeys',
        component: () => import('../views/ApiKeysView.vue'),
        meta: { titleKey: 'nav.apiKeys' },
      },
      {
        path: 'maintenance',
        name: 'Maintenance',
        component: () => import('../views/MaintenanceView.vue'),
        meta: { titleKey: 'nav.maintenance' },
      },
      {
        path: 'silences',
        name: 'Silences',
        component: () => import('../views/SilencesView.vue'),
        meta: { titleKey: 'nav.silences' },
      },
      {
        path: 'oncall',
        name: 'OnCall',
        component: () => import('../views/OnCallView.vue'),
        meta: { titleKey: 'nav.oncall' },
      },
      {
        path: 'audit',
        name: 'Audit',
        component: () => import('../views/AuditView.vue'),
        meta: { titleKey: 'nav.audit' },
      },
      {
        path: 'tls-fleet',
        name: 'TlsFleet',
        component: () => import('../views/TlsFleetView.vue'),
        meta: { titleKey: 'nav.tls_fleet' },
      },
      {
        path: 'incident-groups',
        redirect: '/incidents',
      },
      {
        path: 'probes/:id/timeline',
        name: 'ProbeTimeline',
        component: () => import('../views/ProbeTimelineView.vue'),
        meta: { titleKey: 'nav.probes' },
      },
      {
        path: 'incidents',
        name: 'Incidents',
        component: () => import('../views/IncidentsView.vue'),
        meta: { titleKey: 'nav.incidents' },
      },
      {
        path: 'templates',
        name: 'Templates',
        component: () => import('../views/TemplatesView.vue'),
        meta: { titleKey: 'nav.templates' },
      },
      {
        path: 'graph',
        name: 'DependencyGraph',
        component: () => import('../views/DependencyGraphView.vue'),
        meta: { titleKey: 'nav.graph' },
      },
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('../views/AdminView.vue'),
        meta: { requiresAdmin: true, titleKey: 'nav.admin' },
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

// Auth + setup guard
router.beforeEach(async (to) => {
  // On native builds, force the setup screen until a backend URL is configured.
  if (!isConfigured() && !to.meta.setup) {
    return { name: 'ServerSetup', query: { redirect: to.fullPath } }
  }
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && !auth.isSuperadmin) {
    return { name: 'Dashboard' }
  }
})

// A11Y: announce SPA navigations to assistive tech — per-view document.title
// and focus moved to the content landmark (skipped on initial load, where the
// browser's natural focus is correct).
router.afterEach((to, from) => {
  const { t } = i18n.global
  document.title = to.meta.titleKey ? `${t(to.meta.titleKey)} · WhatIsUp` : 'WhatIsUp'
  if (from.name !== undefined) {
    document.getElementById('main-content')?.focus({ preventScroll: true })
  }
})

export default router
