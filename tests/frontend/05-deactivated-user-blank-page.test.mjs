/**
 * АТАКА 5. Заблокированный сотрудник получает вечно пустую страницу.
 *
 * Сценарий целиком рабочий, без подделки данных:
 *   1. Сотрудник вошёл, страница открыта, токены в localStorage.
 *   2. Администратор жмёт «Заблокировать» (POST /api/users/<id>/set-active/).
 *   3. Сотрудник обновляет страницу.
 *
 * Дальше: SimpleJWT отдаёт 401 «User is inactive» на /api/auth/me/.
 * frontend/js/api.js:112-116 — раз refresh-токен есть, клиент обновляет access.
 * TokenRefreshView проверяет только подпись refresh-токена (в настройках
 * backend/config/settings.py BLACKLIST_AFTER_ROTATION=False, проверки
 * пользователя нет) — обновление проходит успешно.
 * Повтор запроса идёт с retry=false, снова 401, и наружу летит ApiError(401).
 * frontend/js/layout.js:61 — `if (error.status === 401) return null;` — молча.
 *
 * Итог: ни редиректа на страницу входа, ни сообщения, ни очистки сессии.
 * Пользователь смотрит на каркас приложения с пустыми блоками и не понимает,
 * что произошло. Обновление страницы повторяет цикл бесконечно.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { makeFetch, APP_CONFIG } from './helpers/net.mjs';

const html = fs.readFileSync(fileURLToPath(FRONTEND + 'dashboard.html'), 'utf8');
const CACHED = { id: 7, full_name: 'Иван Петров', role: 'EMPLOYEE', role_display: 'Сотрудник' };

const env = installDom({
  html,
  storage: {
    'delivery.access': 'acc',
    'delivery.refresh': 'ref',
    'delivery.user': JSON.stringify(CACHED),
  },
  media: { '(min-width: 1024px)': true, '(max-width: 767px)': false },
});
globalThis.window.APP_CONFIG = APP_CONFIG;

let refreshCalls = 0;
globalThis.fetch = makeFetch({
  '/auth/refresh/': () => {
    refreshCalls += 1;
    return { status: 200, body: { access: `acc${refreshCalls}`, refresh: `ref${refreshCalls}` } };
  },
  '/auth/me/': { status: 401, body: { detail: 'User is inactive' } },
});

const { initLayout } = await import(FRONTEND + 'js/layout.js');
const { tokenStore } = await import(FRONTEND + 'js/api.js');

const user = await initLayout({ active: 'dashboard.html' });
await env.flush();

test('заблокированный сотрудник: refresh проходит, /auth/me/ снова 401', () => {
  console.log('  обращений к /auth/refresh/:', refreshCalls);
  console.log('  initLayout вернул       :', user);
  assert.equal(refreshCalls, 1, 'обновление токена действительно выполнялось');
  assert.equal(user, null, 'страница дальше не грузится');
});

test('пользователя не увели на страницу входа и не показали ни одного сообщения', () => {
  const toast = env.document.querySelector('.toast');
  console.log('  location.href :', globalThis.location.href);
  console.log('  сообщение     :', toast ? toast.textContent : 'нет');
  console.log('  access остался:', JSON.stringify(tokenStore.access));

  assert.match(
    globalThis.location.href,
    /index\.html$/,
    'FAIL: нет редиректа на index.html — сотрудник заперт на нерабочей странице'
  );
  assert.ok(toast, 'FAIL: пользователю не сообщили ничего');
});

test('сессия не очищена -> при следующем открытии всё повторится', () => {
  assert.equal(tokenStore.access, null, 'FAIL: мёртвые токены остались в localStorage');
});

test('на экране есть объяснение, а не пустые блоки', () => {
  const stats = env.document.querySelector('#stats');
  const active = env.document.querySelector('#active-deliveries');
  // Либо контейнеры панели заполнены состоянием, либо вместо них отрисовано
  // сообщение о завершённой сессии. Пустой каркас без объяснения — провал.
  const notice = env.document.querySelector('.app-main .card h1');
  const filled =
    (stats && stats.childNodes.length) || (active && active.childNodes.length);
  console.log('  контейнеры заполнены:', Boolean(filled));
  console.log('  сообщение на экране :', notice ? notice.textContent : 'нет');
  assert.ok(
    filled || notice,
    'FAIL: содержимое панели пустое, никакого состояния ошибки не отрисовано'
  );
});
