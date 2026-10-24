// 離線快取：全部先試網絡（app 更新即刻見到），冇網先用上次嘅
const CACHE = "signals-app-100";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];
// 2026-10-24：新聞、加密等喺 raw.githubusercontent.com（feeds／radar／live 分支），之前跨網站唔理，冇網或者 GitHub 5xx 就成頁讀唔到
const FEED_HOSTS = ["raw.githubusercontent.com"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  const same = url.origin === self.location.origin;
  if (e.request.method !== "GET" || !(same || FEED_HOSTS.includes(url.host))) return;
  // 同一個 key 唔理 ?t= 參數，冇網時都搵到上次嘅 scan.json、news.json
  const key = url.pathname.endsWith(".json") ? (same ? url.pathname : url.origin + url.pathname) : e.request;
  const old = () => caches.match(key).then(r => r || (e.request.mode === "navigate" ? caches.match("index.html") : undefined));
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok){ const c = r.clone(); caches.open(CACHE).then(k => k.put(key, c)); return r; }
    return r.status >= 500 ? old().then(c => c || r) : r;           // GitHub 5xx：用返上次；404 照返（例如未有空投分析）
  }).catch(() => old()));
});
