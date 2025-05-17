// static/sw.js
self.addEventListener('install', (event) => {
  console.log('Service Worker instalado');
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('Service Worker activado');
});

self.addEventListener('fetch', (event) => {
  // Estrategia básica de caché (puedes mejorarla)
  event.respondWith(fetch(event.request).catch(() => {
    return new Response('Offline');
  }));
});
