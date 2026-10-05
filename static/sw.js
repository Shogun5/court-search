// 外殼檔案先快取 → 離線也能開啟；API 走網路優先，失敗時用上次的結果。
const VERSION = "v3";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.json", "courts.json",
  "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open("shell-" + VERSION).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;

  if (url.pathname.includes("/api/")) {
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open("api-" + VERSION).then((c) => c.put(e.request, copy)); }
      return res;
    }).catch(() => caches.match(e.request).then((r) => r ||
      new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } }))));
    return;
  }

  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then((r) => r || fetch(e.request)));
});
