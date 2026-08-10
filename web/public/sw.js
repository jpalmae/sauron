/* Sauron service worker: Web Push notifications only (no offline caching). */
self.addEventListener("push", (event) => {
  let data = { title: "Sauron", body: "", url: "/" };
  try {
    data = { ...data, ...event.data.json() };
  } catch (e) { /* keep defaults */ }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/brand/favicon.svg",
      badge: "/brand/favicon.svg",
      data: { url: data.url },
      tag: "sauron-alert",
      renotify: true,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
