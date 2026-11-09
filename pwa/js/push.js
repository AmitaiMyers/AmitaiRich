// Phone notifications: subscribe this device to Web Push and show the subscription JSON,
// which the owner stores once as the GitHub secret PUSH_SUBSCRIPTION (notify.py sends to it).

import { VAPID_PUBLIC_KEY } from './push-config.js';
import { h } from './ui.js';

const isSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

function urlBase64ToUint8Array(base64url) {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

async function subscribe() {
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') throw new Error(`Notification permission is "${permission}".`);
  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  return existing || registration.pushManager.subscribe({
    userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
  });
}

async function testNotification() {
  const registration = await navigator.serviceWorker.ready;
  await registration.showNotification('Roof Signals · test', {
    body: 'Notifications work on this device.', icon: 'icons/icon-192.png', data: { url: './#/today' },
  });
}

function subscriptionPanel(subscription) {
  const json = JSON.stringify(subscription.toJSON());
  const status = h('span', { class: 'muted small' });
  return h('div', {},
    h('p', { class: 'small', text: 'This device is subscribed. One-time setup: copy the text below and save it in GitHub → '
      + 'repo Settings → Secrets and variables → Actions → New repository secret, name PUSH_SUBSCRIPTION.' }),
    h('textarea', { readonly: true, rows: 4, text: json }),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'primary', text: 'Copy', onclick: async () => {
        await navigator.clipboard.writeText(json);
        status.textContent = 'Copied.';
      } }),
      h('button', { type: 'button', text: 'Send a test notification', onclick: testNotification }),
      status));
}

/** The "Daily notifications" card for the Today page. */
export function notificationsCard() {
  const body = h('div');
  const card = h('details', { class: 'card section' }, h('summary', { text: 'Daily phone notifications' }), body);
  if (!isSupported()) {
    body.append(h('p', { class: 'small muted', text: 'This browser does not support push notifications. '
      + 'On iPhone: open this site in Safari → Share → Add to Home Screen, then open it from the Home Screen (iOS 16.4+).' }));
    return card;
  }
  const error = h('p', { class: 'small down' });
  const enable = h('button', { type: 'button', class: 'primary', text: 'Enable notifications on this device', onclick: async () => {
    error.textContent = '';
    try {
      body.replaceChildren(subscriptionPanel(await subscribe()));
    } catch (failure) {   // permission denied / push service unreachable: tell the user, keep the button
      error.textContent = failure.message;
    }
  } });
  body.append(h('p', { class: 'small muted', text: 'One push each weekday evening with the new v0 / v7 names.' }), enable, error);
  navigator.serviceWorker.ready
    .then((registration) => registration.pushManager.getSubscription())
    .then((subscription) => { if (subscription) body.replaceChildren(subscriptionPanel(subscription)); });
  return card;
}
