// 離線快取：全部先試網絡（app 更新即刻見到），冇網先用上次嘅
const CACHE = "signals-app-45";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;
  // 同一個 key 唔理 ?t= 參數，冇網時都搵到上次嘅 scan.json
  const key = url.pathname.endsWith(".json") ? url.pathname : e.request;
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const c = r.clone(); caches.open(CACHE).then(k => k.put(key, c)); }
    return r;
  }).catch(() => caches.match(key).then(r => r || (e.request.mode === "navigate" ? caches.match("index.html") : undefined))));
});
