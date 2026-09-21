'use strict';

const legacy = {
  chat: '/dashboard/models',
  models: '/pricing',
  keys: '/keys',
  wallet: '/wallet',
  login: '/login',
  register: '/register',
  account: '/profile',
  operations: '/dashboard/overview',
};
function routeLegacy() {
  const target = legacy[location.hash.slice(1)];
  if (target) location.replace(target);
  else if (location.hash === '#developer') location.replace('#guide');
}
routeLegacy();
window.addEventListener('hashchange', routeLegacy);

const safeTransport = location.protocol === 'https:' ||
  (location.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(location.hostname));
if (safeTransport) {
  const base = location.origin + '/v1';
  document.querySelectorAll('[data-base-url]').forEach(element => { element.textContent = base; });
  document.getElementById('api-example').textContent =
    `POST ${base}/chat/completions\nAuthorization: Bearer YOUR_CUSTOMER_KEY\nContent-Type: application/json\n\n` +
    JSON.stringify({ model: 'YOUR_AUTHORIZED_MODEL', messages: [{ role: 'user', content: '你好' }] }, null, 2);
}

// Only restore a hinted session; never persist tokens or call a model from this page.
const entry = document.getElementById('account-entry');
let generation = 0;
function signedOut() {
  generation += 1;
  entry.textContent = '登录账户';
  entry.href = '/login';
}
async function restoreAccount() {
  const epoch = ++generation;
  entry.textContent = '正在确认账户…';
  const restore = async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/user/auth/refresh', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        redirect: 'error', signal: controller.signal,
      });
      if (epoch !== generation) return;
      if (response.status === 401) { signedOut(); return; }
      if (!response.ok) throw new Error('Session unavailable');
      const result = await response.json();
      if (epoch !== generation) return;
      if (result.success !== true || !result.data?.user?.id) throw new Error('Session unavailable');
      entry.textContent = '我的账户';
      entry.href = '/profile';
    } finally {
      clearTimeout(timeout);
    }
  };
  try {
    if (navigator.locks?.request) await navigator.locks.request('new-api:auth-refresh', restore);
    else await restore();
  } catch {
    if (epoch === generation) {
      entry.textContent = '重新确认账户';
      entry.href = '/login';
    }
  }
}
function checkHint() {
  if (safeTransport && document.cookie.split(';').some(part => part.trim() === 'new_api_has_session=1')) {
    void restoreAccount();
  } else signedOut();
}
checkHint();
window.addEventListener('pageshow', event => { if (event.persisted) checkHint(); });
window.addEventListener('focus', checkHint);

function onSessionEvent(event) {
  if (!event || typeof event.timestamp !== 'number' ||
      Math.abs(Date.now() - event.timestamp) >= 60000) return;
  if (event.kind === 'signed_out') signedOut();
  else if (event.kind === 'authenticated') checkHint();
}
if (typeof BroadcastChannel !== 'undefined') {
  const channel = new BroadcastChannel('new-api:auth-session');
  channel.addEventListener('message', event => onSessionEvent(event.data));
} else {
  window.addEventListener('storage', event => {
    if (event.key !== 'new-api:auth-session:event' || !event.newValue) return;
    try { onSessionEvent(JSON.parse(event.newValue)); }
    catch { console.warn('Ignored malformed account synchronization event'); }
  });
}
