// Minimal offline-friendly service worker for the Garage PWA.
const CACHE = "garage-v1";
const ASSETS = ["/", "/static/styles.css", "/static/manifest.json", "/static/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // never cache POSTs (form submissions)
  // Network-first for navigation so data stays fresh; fall back to cache offline.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/")));
    return;
  }
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});
