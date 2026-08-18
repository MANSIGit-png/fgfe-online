// Service Worker для мгновенной загрузки
const CACHE_NAME = 'ftfe_cache_v3';
const STATIC_CACHE_NAME = 'ftfe_static_v3';
const API_CACHE_NAME = 'ftfe_api_v3';

// Файлы для кеширования
const STATIC_FILES = [
    '/',
    '/index.html',
    '/profile.html',
    '/settings.html',
    '/style.css',
    '/script.js',
    '/carousel.js',
    '/chart.js',
    '/webapp/content.json'
];

// Устанавливаем Service Worker и кешируем статику
self.addEventListener('install', event => {
    console.log('Service Worker установлен');
    event.waitUntil(
        Promise.all([
            caches.open(STATIC_CACHE_NAME).then(cache => {
                return cache.addAll(STATIC_FILES);
            }),
            caches.open(API_CACHE_NAME)
        ]).then(() => self.skipWaiting())
    );
});

// Активация - очищаем старые кеши
self.addEventListener('activate', event => {
    console.log('Service Worker активирован');
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(key => key !== STATIC_CACHE_NAME && key !== API_CACHE_NAME)
                    .map(key => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Перехватываем запросы
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // API запросы - кешируем на 5 минут
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            caches.open(API_CACHE_NAME).then(async cache => {
                try {
                    const response = await fetch(event.request);
                    // Кешируем только успешные ответы
                    if (response.status === 200) {
                        cache.put(event.request, response.clone());
                    }
                    return response;
                } catch (e) {
                    // Если нет сети - берем из кеша
                    const cached = await cache.match(event.request);
                    if (cached) return cached;
                    throw e;
                }
            })
        );
        return;
    }

    // Статические файлы (HTML, CSS, JS)
    if (STATIC_FILES.some(file => event.request.url.includes(file))) {
        event.respondWith(
            caches.match(event.request).then(cached => {
                if (cached) {
                    // Обновляем кеш в фоне
                    fetch(event.request).then(response => {
                        if (response.status === 200) {
                            caches.open(STATIC_CACHE_NAME).then(cache => {
                                cache.put(event.request, response);
                            });
                        }
                    }).catch(() => {});
                    return cached;
                }
                return fetch(event.request);
            })
        );
        return;
    }

    // Остальные запросы - сеть с fallback на кеш
    event.respondWith(
        fetch(event.request).catch(async () => {
            const cached = await caches.match(event.request);
            if (cached) return cached;
            // Fallback для изображений
            if (event.request.url.match(/\.(jpg|jpeg|png|gif|webp)$/)) {
                return caches.match('/sticer/ezgif.com-gif-maker.gif');
            }
            return new Response('Офлайн режим', { status: 503 });
        })
    );
});
