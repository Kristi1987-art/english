/* ============================================================
   Офлайн для «Звуков и Блоков».

   Приложение — один файл на полтора мегабайта, и почти всё в нём звук.
   Тянуть его каждый раз незачем и негде: заниматься ребёнок будет в машине,
   у бабушки и в самолёте. Service worker кладёт файл в кэш при первом
   открытии и дальше отдаёт его из кэша всегда, сеть при этом не нужна.

   Стратегия одна на всё: отдаём из кэша сразу, а сеть спрашиваем в фоне
   и складываем ответ на следующий раз. Для учебного приложения это верный
   размен — открывается мгновенно и работает без сети, а новая версия
   приезжает к следующему запуску.

   Шрифты Google не лежат в списке заранее: их адреса зависят от браузера.
   Зато они складываются в тот же кэш при первой загрузке, поэтому со второго
   запуска буквы остаются Andika и без сети.
   ============================================================ */

const V = 'zvuki-2026-08-31';

const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon-192.png',
  './icon-512.png',
];

const FONTS = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;

const keep = req => req.url.startsWith(self.location.origin) || FONTS.test(req.url);

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(V)
      .then(c => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(names => Promise.all(names.filter(n => n !== V).map(n => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if(req.method !== 'GET') return;

  e.respondWith((async () => {
    const cache = await caches.open(V);
    const hit = await cache.match(req);

    const net = fetch(req).then(res => {
      if(res && res.ok && keep(req)) cache.put(req, res.clone());
      return res;
    }).catch(() => null);

    if(hit){
      e.waitUntil(net);            /* обновляем молча, к следующему запуску */
      return hit;
    }

    const res = await net;
    if(res) return res;

    /* Сети нет и в кэше именно этого адреса тоже: если человек открывает
       приложение, отдаём сохранённую страницу, а не ошибку. */
    if(req.mode === 'navigate'){
      const shell = await cache.match('./') || await cache.match('./index.html');
      if(shell) return shell;
    }
    return Response.error();
  })());
});
