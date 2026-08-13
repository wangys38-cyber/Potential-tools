/* Service Worker v4.0-pwa — App Shell 模式 */
const VERSION = 'v4.0-pwa';
const SHELL_CACHE = `app-shell-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;

// App Shell 预缓存清单：核心页面 + 静态资源
const PRECACHE_URLS = [
  '/', '/noteNB/', '/merit', '/settings',
  '/static/css/theme.css', '/static/js/components.js'
];

// install：预缓存 App Shell，跳过 waiting
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// activate：清理旧缓存，立即 claim
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
          .map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

// fetch：运行时缓存策略
self.addEventListener('fetch', (event) => {
  const { request } = event;
  // 仅处理 GET；POST 等直接放行不缓存
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // API 请求不缓存，passthrough
  if (url.pathname.startsWith('/api/')) return;

  const accept = request.headers.get('accept') || '';
  const dest = request.destination;

  if (dest === 'document' || accept.includes('text/html')) {
    event.respondWith(networkFirst(request));           // HTML → NetworkFirst
  } else if (dest === 'image' || accept.includes('image/')) {
    event.respondWith(cacheFirst(request));             // 图片 → CacheFirst
  } else if (dest === 'style' || dest === 'script' ||
             accept.includes('text/css') || accept.includes('javascript')) {
    event.respondWith(staleWhileRevalidate(request));   // CSS/JS → SWR
  }
});

// NetworkFirst：先网络，失败回退缓存
async function networkFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  try {
    const resp = await fetch(request);
    if (resp && resp.ok) cache.put(request, resp.clone());
    return resp;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    const shell = await caches.match('/');   // 离线兜底 App Shell
    if (shell) return shell;
    throw err;
  }
}

// CacheFirst：优先缓存，无则网络获取并写入
async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const resp = await fetch(request);
  if (resp && resp.ok) cache.put(request, resp.clone());
  return resp;
}

// StaleWhileRevalidate：先返回缓存，后台并发更新
async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((resp) => {
    if (resp && resp.ok) cache.put(request, resp.clone());
    return resp;
  }).catch(() => cached);
  return cached || network;
}
