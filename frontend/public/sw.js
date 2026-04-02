// WhatIsUp Service Worker — handles Web Push notifications

self.addEventListener('push', (event) => {
  let data = { title: 'WhatIsUp', body: 'New notification', url: '/' }
  if (event.data) {
    try { data = event.data.json() } catch {}
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/favicon.ico',
      badge: '/favicon.ico',
      data: { url: data.url || '/' },
      requireInteraction: false,
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const rawUrl = event.notification.data?.url || '/'
  // Validate same-origin before navigation
  let url
  try {
    const parsed = new URL(rawUrl, self.location.origin)
    url = parsed.origin === self.location.origin ? parsed.href : '/'
  } catch { url = '/' }
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (new URL(client.url).origin === self.location.origin) {
          client.focus()
          client.navigate(url)
          return
        }
      }
      return clients.openWindow(url)
    })
  )
})
