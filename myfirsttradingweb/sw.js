// sw.js — Service Worker cho CuShin Terminal
// Chạy NỀN, độc lập với tab trình duyệt — đây là lý do push hoạt động ngay cả khi đã đóng tab.
// File này PHẢI nằm ở thư mục gốc của site (cùng cấp với index.html) để có phạm vi (scope)
// bao trùm toàn bộ trang.

self.addEventListener('install', (event) => {
  self.skipWaiting(); // kích hoạt Service Worker mới ngay, không cần đợi đóng hết tab cũ
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Nhận sự kiện push từ server (autoscreener.py gửi qua Web Push khi có tín hiệu mới)
self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'CuShin Terminal', body: event.data ? event.data.text() : 'Có tín hiệu mới' };
  }

  const title = data.title || '🔥 CuShin Terminal';
  const options = {
    body: data.body || 'Có tín hiệu giao dịch mới',
    icon: 'https://cdn-icons-png.flaticon.com/512/4341/4341139.png', // icon mặc định, có thể đổi
    badge: 'https://cdn-icons-png.flaticon.com/512/4341/4341139.png',
    tag: 'cushin-signal', // gộp thông báo trùng tag thay vì chồng chất nếu bắn liên tiếp
    renotify: true,
    data: { url: data.url || '/' },
    vibrate: [120, 60, 120],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Khi người dùng bấm vào thông báo -> mở (hoặc điều hướng) tab tới đúng URL kèm profile/symbol
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          if ('navigate' in client) {
            try { await client.navigate(targetUrl); } catch (e) { /* một số trình duyệt không hỗ trợ navigate() */ }
          }
          return client.focus();
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});
