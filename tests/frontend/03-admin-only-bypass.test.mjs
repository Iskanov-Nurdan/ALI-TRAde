/**
 * АТАКА 3. adminOnly не проверяется, если /auth/me/ не ответил.
 *
 * frontend/js/layout.js:60-73 — в catch, если кэшированный пользователь есть,
 * показывается тост и выполнение продолжается: `if (!user) return null;` не
 * срабатывает, и initLayout возвращает КЭШИРОВАННОГО пользователя.
 * Проверка `adminOnly && user.role !== 'ADMIN'` (строка 54) при этом пропущена —
 * она стоит только на успешной ветке.
 *
 * Кто угодно, у кого есть валидная сессия обычного сотрудника, может выставить
 *   localStorage['delivery.user'] = '{"role":"ADMIN","full_name":"…"}'
 * и заблокировать один запрос /api/auth/me/ (офлайн, блокировка URL в devtools,
 * упавший бэкенд) — и users.html / settings.html / points.html / reports.html /
 * audit.html отрисуются целиком, обработчики повесятся, initLayout вернёт
 * «администратора». Тот же путь срабатывает и без злого умысла — у сотрудника,
 * которого только что понизили в правах: роль в кэше устарела, сеть моргнула,
 * админ-раздел меню остался на месте.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { makeFetch, APP_CONFIG } from './helpers/net.mjs';

const usersHtml = fs.readFileSync(fileURLToPath(FRONTEND + 'users.html'), 'utf8');
const FORGED = { id: 7, full_name: 'Обычный сотрудник', role: 'ADMIN', role_display: 'Администратор' };

let env = installDom({
  html: usersHtml,
  storage: {
    'delivery.access': 'acc',
    'delivery.refresh': 'ref',
    'delivery.user': JSON.stringify(FORGED),
  },
  media: { '(min-width: 1024px)': true, '(max-width: 767px)': false },
});
globalThis.window.APP_CONFIG = APP_CONFIG;
// /auth/me/ недоступен: fetch падает -> api.js делает ApiError со status 0
globalThis.fetch = makeFetch({});

const { initLayout } = await import(FRONTEND + 'js/layout.js');

test('adminOnly: /auth/me/ недоступен + подделанная роль в localStorage -> админ-страница рендерится', async () => {
  const user = await initLayout({ active: 'users.html', adminOnly: true });
  await env.flush();

  const denied = env.document.querySelector('.app-main .card h1');
  console.log('  initLayout вернул:', user && user.role);
  console.log('  data-role на <html>:', env.document.documentElement.dataset.role);
  console.log('  экран «Доступ запрещён»:', denied ? denied.textContent : 'нет');
  console.log('  таблица сотрудников на месте:', Boolean(env.document.querySelector('#users-table, #users-list, table')));

  assert.equal(
    user,
    null,
    'FAIL: initLayout вернул пользователя — страница users.js продолжит работу как для администратора'
  );
});

test('adminOnly: экран «Доступ запрещён» не показан, каркас админки собран', async () => {
  const main = env.document.querySelector('.app-main');
  const heading = main.querySelector('h1');
  console.log('  заголовок раздела:', heading && heading.textContent);
  assert.equal(
    heading && heading.textContent,
    'Доступ запрещён',
    'FAIL: вместо запрета отрисован обычный админ-раздел'
  );
});

test('data-role остаётся ADMIN -> админ-раздел меню виден (CSS :root:not([data-role="ADMIN"]) .sidebar__admin)', () => {
  assert.notEqual(
    env.document.documentElement.dataset.role,
    'ADMIN',
    'FAIL: <html data-role="ADMIN"> — по правилу css/styles.css:493 весь блок .sidebar__admin виден'
  );
});

test('КОНТРОЛЬ: когда /auth/me/ отвечает, понижение роли обрабатывается верно', async () => {
  env = installDom({
    html: usersHtml,
    storage: {
      'delivery.access': 'acc',
      'delivery.refresh': 'ref',
      'delivery.user': JSON.stringify(FORGED),
    },
    media: { '(min-width: 1024px)': true, '(max-width: 767px)': false },
  });
  globalThis.window.APP_CONFIG = APP_CONFIG;
  globalThis.fetch = makeFetch({
    '/auth/me/': { status: 200, body: { id: 7, full_name: 'Обычный сотрудник', role: 'EMPLOYEE', role_display: 'Сотрудник' } },
  });

  const user = await initLayout({ active: 'users.html', adminOnly: true });
  assert.equal(user, null, 'при живом сервере доступ закрыт');
  assert.equal(env.document.querySelector('.app-main h1').textContent, 'Доступ запрещён');
});
