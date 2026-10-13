const CACHE_NAME = 'globalinfra-phase7-v2';
const APP_SHELL = ['/', '/field', '/offline', '/favicon.svg', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/backend/')) return;

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
          return response;
        })
        .catch(async () => (await caches.match(request)) || (await caches.match('/offline')))
    );
    return;
  }

  if (url.pathname.startsWith('/_next/static/') || url.pathname === '/favicon.svg' || url.pathname.startsWith('/icons/')) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(response => {
        if (response.ok) caches.open(CACHE_NAME).then(cache => cache.put(request, response.clone()));
        return response;
      }))
    );
  }
});

self.addEventListener('sync', event => {
  if (event.tag !== 'globalinfra-field-sync') return;
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(clients => {
    clients.forEach(client => client.postMessage({type:'GLOBALINFRA_FIELD_SYNC'}));
  }));
});
