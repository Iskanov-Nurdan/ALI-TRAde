/**
 * АТАКА 1. initLayout: каркас страницы собирается ТОЛЬКО из кэша localStorage.
 *
 * frontend/js/layout.js:39-45 — drawShell(user) вызывается внутри `if (user)`.
 * Если в localStorage нет ключа delivery.user (битый JSON, приватный режим,
 * ручная чистка, обновление формата), но access-токен на месте, то после
 * успешного api.me() выполняется только renderSidebar (строка 59).
 * renderTopbar / setupFilters / hydrateIcons / applyBranding / enhanceSelects /
 * watchSelects не вызываются НИКОГДА.
 *
 * Для пользователя: пустой <header id="app-header"> — нет кнопки-бургера,
 * а на экране < 1024px сайдбар уведён за край (transform: translate3d(-100%,0,0)),
 * открыть его нечем. Навигация полностью недоступна. Плюс нет переключателя темы,
 * нет глобального поиска, ни одна иконка не подставлена.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { makeFetch, APP_CONFIG } from './helpers/net.mjs';

const html = fs.readFileSync(fileURLToPath(FRONTEND + 'dashboard.html'), 'utf8');
const ME = { id: 1, full_name: 'Иван Петров', role: 'EMPLOYEE', role_display: 'Сотрудник' };

globalThis.APP_CONFIG = APP_CONFIG;
let env = installDom({
  html,
  storage: { 'delivery.access': 'acc', 'delivery.refresh': 'ref' }, // delivery.user отсутствует
  media: { '(min-width: 1024px)': false, '(max-width: 767px)': true },
});
globalThis.window.APP_CONFIG = APP_CONFIG;
globalThis.fetch = makeFetch({ '/auth/me/': { status: 200, body: ME } });

const { initLayout } = await import(FRONTEND + 'js/layout.js');

test('нет кэша пользователя -> верхняя панель остаётся пустой, меню открыть нечем', async () => {
  const user = await initLayout({ active: 'dashboard.html' });
  await env.flush();

  assert.equal(user.role, 'EMPLOYEE', 'api.me() отработал, пользователь получен');

  const header = env.document.querySelector('#app-header');
  const burger = env.document.querySelector('.topbar__menu');
  const overlay = env.document.querySelector('.sidebar-overlay');
  const search = env.document.querySelector('#global-search');

  console.log('  детей в #app-header:', header.childNodes.length);
  console.log('  кнопка-бургер:', Boolean(burger));
  console.log('  затемнение (overlay):', Boolean(overlay));
  console.log('  поле поиска:', Boolean(search));

  assert.ok(burger, 'FAIL: кнопки открытия меню нет — на мобильном сайдбар недостижим');
  assert.ok(overlay, 'FAIL: затемнения нет — обработчики меню не созданы');
  assert.ok(search, 'FAIL: глобального поиска нет');
  assert.ok(header.childNodes.length > 0, 'FAIL: #app-header пуст');
});

test('нет кэша пользователя -> иконки и брендинг не подставлены', async () => {
  const notReady = env.document
    .querySelectorAll('[data-icon]')
    .filter((node) => !node.hasAttribute('data-icon-ready'));
  console.log('  элементов [data-icon] без data-icon-ready:', notReady.length);
  assert.equal(notReady.length, 0, 'FAIL: hydrateIcons не вызывался — иконки не отрисованы');
});

test('КОНТРОЛЬ: при наличии кэша всё собирается — значит ломает именно отсутствие кэша', async () => {
  env = installDom({
    html,
    storage: {
      'delivery.access': 'acc',
      'delivery.refresh': 'ref',
      'delivery.user': JSON.stringify(ME),
    },
    media: { '(min-width: 1024px)': false, '(max-width: 767px)': true },
  });
  globalThis.window.APP_CONFIG = APP_CONFIG;
  globalThis.fetch = makeFetch({ '/auth/me/': { status: 200, body: ME } });

  await initLayout({ active: 'dashboard.html' });
  await env.flush();

  assert.ok(env.document.querySelector('.topbar__menu'), 'с кэшем бургер есть');
  assert.ok(env.document.querySelector('.sidebar-overlay'), 'с кэшем затемнение есть');
  const notReady = env.document
    .querySelectorAll('[data-icon]')
    .filter((node) => !node.hasAttribute('data-icon-ready'));
  assert.equal(notReady.length, 0, 'с кэшем иконки подставлены');
});
