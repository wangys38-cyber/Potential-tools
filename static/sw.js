/* Service Worker v6.0 — 增强离线支持 */
const VERSION = 'v6.0-offline';
const SHELL_CACHE = `app-shell-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;
const API_CACHE = `api-${VERSION}`;

// 核心页面（离线可访问）
const CORE_PAGES = [
  '/',
  '/excel-analysis',
  '/log-analyzer',
  '/notes',
  '/plan-generator',
  '/meeting-minutes',
  '/settings'
];

// App Shell 预缓存清单
const PRECACHE_URLS = [
  '/',
  '/static/css/theme.css',
  '/static/css/polish.css',
  '/static/css/design-system.css',
  '/static/js/components.js',
  '/static/js/v5-sync.js',
  '/static/manifest.json',
  '/static/offline.html'
];

// install：预缓存 App Shell，跳过 waiting
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// activate：清理旧缓存，立即 claim
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

// fetch：运行时缓存策略
self.addEventListener('fetch', (event) => {
  const { request } = event;
  // 仅处理 GET
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // 非同源请求不处理
  if (url.origin !== self.location.origin) return;

  const accept = request.headers.get('accept') || '';
  const dest = request.destination;

  // API 请求 → NetworkFirst，离线返回缓存或错误
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstWithCache(request, API_CACHE));
    return;
  }

  // HTML 页面 → StaleWhileRevalidate，离线显示缓存
  if (dest === 'document' || accept.includes('text/html')) {
    event.respondWith(staleWhileRevalidatePage(request));
    return;
  }

  // 图片 → CacheFirst
  if (dest === 'image' || accept.includes('image/')) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // CSS/JS/字体 → CacheFirst（静态资源长期缓存）
  if (dest === 'style' || dest === 'script' ||
      accept.includes('text/css') || accept.includes('javascript') ||
      url.pathname.match(/\.(css|js|woff2?|ttf|eot)$/)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // 其他 → StaleWhileRevalidate
  event.respondWith(staleWhileRevalidate(request));
});

// ===== 策略实现 =====

// HTML 页面 SWR：离线时返回缓存，无缓存返回 offline.html
async function staleWhileRevalidatePage(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((resp) => {
    if (resp && resp.ok) cache.put(request, resp.clone());
    return resp;
  }).catch(() => cached);

  if (cached) return cached;
  try {
    return await network;
  } catch (e) {
    // 离线兜底
    const offline = await caches.match('/static/offline.html');
    if (offline) return offline;
    return new Response('离线状态，请检查网络连接', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

// NetworkFirst（带 API 缓存）：先网络，失败回退缓存
async function networkFirstWithCache(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const resp = await fetch(request);
    if (resp && resp.ok) {
      // 只缓存 GET 请求的成功响应
      cache.put(request, resp.clone()).catch(() => {});
    }
    return resp;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ status: 'error', error: '网络不可用', offline: true }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// CacheFirst：优先缓存，无则网络获取并写入
async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const resp = await fetch(request);
    if (resp && resp.ok) cache.put(request, resp.clone()).catch(() => {});
    return resp;
  } catch (e) {
    return cached || new Response('', { status: 404 });
  }
}

// StaleWhileRevalidate：先返回缓存，后台并发更新
async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((resp) => {
    if (resp && resp.ok) cache.put(request, resp.clone()).catch(() => {});
    return resp;
  }).catch(() => cached);
  return cached || network;
}
