/**
 * АТАКА 7. Закрытое мобильное меню остаётся в порядке обхода Tab.
 *
 * frontend/css/styles.css:311-341 — .sidebar убирается за край экрана только
 * через transform: translate3d(-100%, 0, 0). Ни display, ни visibility, ни inert.
 * frontend/js/layout.js:141-147 — setMenu переключает исключительно классы и
 * aria-expanded на кнопке. Сайдбар не получает ни hidden, ни inert,
 * ни aria-hidden; фокус при открытии внутрь панели не переводится,
 * при закрытии на кнопку не возвращается.
 *
 * Для пользователя с клавиатуры или скринридером на экране < 1024px:
 * после кнопки-бургера Tab уходит в 9 ссылок навигации и кнопку «Выйти»,
 * которых на экране нет. Ловушки фокуса у открытого меню тоже нет — Tab
 * из открытого меню уводит в контент под затемнением.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { makeFetch, APP_CONFIG } from './helpers/net.mjs';

const html = fs.readFileSync(fileURLToPath(FRONTEND + 'dashboard.html'), 'utf8');
const css = fs.readFileSync(fileURLToPath(FRONTEND + 'css/styles.css'), 'utf8');
const ME = { id: 1, full_name: 'Иван Петров', role: 'EMPLOYEE', role_display: 'Сотрудник' };

const env = installDom({
  html,
  storage: {
    'delivery.access': 'acc',
    'delivery.refresh': 'ref',
    'delivery.user': JSON.stringify(ME),
  },
  media: { '(min-width: 1024px)': false, '(max-width: 767px)': true }, // телефон
});
globalThis.window.APP_CONFIG = APP_CONFIG;
globalThis.fetch = makeFetch({ '/auth/me/': { status: 200, body: ME } });

const { initLayout } = await import(FRONTEND + 'js/layout.js');
await initLayout({ active: 'dashboard.html' });
await env.flush();

const doc = env.document;
const sidebar = doc.querySelector('#app-sidebar');
const burger = doc.querySelector('.topbar__menu');

test('CSS: панель прячется только сдвигом — из потока фокуса не исключается', () => {
  const rule = css.match(/\n\.sidebar\s*\{[^}]*\}/);
  assert.ok(rule, 'правило .sidebar найдено');
  console.log('  скрытие через:', /transform:\s*translate3d\(-100%/.test(rule[0]) ? 'transform' : '?');
  assert.match(
    rule[0],
    /visibility:\s*hidden|display:\s*none/,
    'FAIL: .sidebar уводится за экран только transform — ссылки остаются кликабельными для Tab'
  );
});

test('меню закрыто: сайдбар не помечен как недоступный', () => {
  console.log('  sidebar.hidden      :', sidebar.hidden);
  console.log('  sidebar[inert]      :', sidebar.hasAttribute('inert'));
  console.log('  sidebar[aria-hidden]:', sidebar.getAttribute('aria-hidden'));
  console.log('  ссылок в панели     :', sidebar.querySelectorAll('a, button').length);
  assert.ok(
    sidebar.hidden || sidebar.hasAttribute('inert') || sidebar.getAttribute('aria-hidden') === 'true',
    'FAIL: закрытое меню остаётся в порядке обхода Tab — фокус уходит на невидимые ссылки'
  );
});

test('меню открыто: фокус не переносится внутрь панели', () => {
  burger.dispatchEvent(new Event('click', { bubbles: true }));
  console.log('  sidebar--open        :', sidebar.classList.contains('sidebar--open'));
  console.log('  body.has-menu-open   :', doc.body.classList.contains('has-menu-open'));
  console.log('  activeElement внутри :', Boolean(doc.activeElement && doc.activeElement.closest('#app-sidebar')));
  assert.ok(sidebar.classList.contains('sidebar--open'), 'меню действительно открылось');
  assert.ok(
    doc.activeElement && doc.activeElement.closest('#app-sidebar'),
    'FAIL: меню открыто, а фокус остался снаружи — с клавиатуры до пунктов не добраться предсказуемо'
  );
});
