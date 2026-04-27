'use strict';
const cacheName = 'threadbot-v1';
const resourcesToCache = [];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(cacheName).then((cache) => cache.addAll(resourcesToCache)));
});
