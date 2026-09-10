/**
 * АТАКА 4. Обновление access-токена в js/api.js.
 *
 * a) frontend/js/api.js:83-87 — fetch внутри refreshAccessToken НЕ обёрнут в try,
 *    в отличие от основного fetch (строки 102-110). Если связь пропала именно в
 *    момент обновления токена, наружу летит системный TypeError, а не ApiError:
 *      - error.status === undefined -> layout.js:61 не распознаёт 401,
 *        на страницу входа никто не уводит;
 *      - страницы делают renderError(box, error.message) — пользователь видит
 *        английский технический текст вместо русского сообщения.
 *
 * b) frontend/js/api.js:112 — ветка обновления требует `tokenStore.refresh`.
 *    Если refresh-токена нет, а access протух, 401 просто превращается в ошибку:
 *    ни очистки хранилища, ни редиректа на index.html. initLayout ловит 401 и
 *    молча возвращает null (layout.js:61) — пользователь остаётся на пустой
 *    странице без единого сообщения и без возможности переавторизоваться.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { installDom } from './helpers/mini-dom.mjs';
import { makeFetch, APP_CONFIG } from './helpers/net.mjs';
import { FRONTEND } from './helpers/mini-dom.mjs';

const env = installDom({
  storage: { 'delivery.access': 'dead', 'delivery.refresh': 'ref' },
});
globalThis.window.APP_CONFIG = APP_CONFIG;

const { api, ApiError, tokenStore } = await import(FRONTEND + 'js/api.js');

test('обрыв связи во время refresh: наружу летит не ApiError, а системный TypeError', async () => {
  globalThis.fetch = makeFetch({
    '/auth/me/': { status: 401, body: { detail: 'token expired' } },
    // маршрута /auth/refresh/ нет -> makeFetch бросает TypeError, как настоящий fetch без сети
  });

  let caught = null;
  try {
    await api.me();
  } catch (error) {
    caught = error;
  }

  console.log('  класс ошибки :', caught && caught.constructor.name);
  console.log('  error.status :', caught && caught.status);
  console.log('  error.message:', caught && caught.message);

  assert.ok(
    caught instanceof ApiError,
    'FAIL: ошибка не ApiError — layout.js:61 (error.status === 401) её не узнает, редиректа на вход не будет'
  );
  assert.match(
    caught.message,
    /[А-Яа-яЁё]/,
    'FAIL: пользователю уйдёт технический текст на английском'
  );
});

test('401 без refresh-токена: ни очистки сессии, ни редиректа на index.html', async () => {
  env.storage.removeItem('delivery.refresh');
  globalThis.location.href = 'http://localhost/dashboard.html';
  globalThis.location.pathname = '/dashboard.html';

  globalThis.fetch = makeFetch({ '/auth/me/': { status: 401, body: { detail: 'token expired' } } });

  let caught = null;
  try {
    await api.me();
  } catch (error) {
    caught = error;
  }

  console.log('  error.status      :', caught && caught.status);
  console.log('  access в хранилище:', JSON.stringify(tokenStore.access));
  console.log('  location.href     :', globalThis.location.href);

  assert.equal(tokenStore.access, null, 'FAIL: протухший access остался в localStorage');
  assert.match(
    globalThis.location.href,
    /index\.html$/,
    'FAIL: редиректа на страницу входа нет — пользователь застрял на пустом экране'
  );
});

test('КОНТРОЛЬ: при живом refresh запрос повторяется и завершается успешно', async () => {
  env.storage.setItem('delivery.access', 'dead');
  env.storage.setItem('delivery.refresh', 'ref');
  let refreshed = false;
  globalThis.fetch = makeFetch({
    '/auth/refresh/': () => {
      refreshed = true;
      return { status: 200, body: { access: 'fresh', refresh: 'ref2' } };
    },
    '/auth/me/': ({ options }) =>
      options.headers.Authorization === 'Bearer fresh'
        ? { status: 200, body: { id: 1, role: 'EMPLOYEE', full_name: 'Иван' } }
        : { status: 401, body: { detail: 'expired' } },
  });

  const me = await api.me();
  assert.equal(refreshed, true);
  assert.equal(me.role, 'EMPLOYEE');
});
