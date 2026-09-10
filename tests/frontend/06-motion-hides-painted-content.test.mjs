/**
 * АТАКА 6. Уже нарисованный контент гасится после ответа сервера.
 *
 * frontend/js/layout.js:71 — revealIn(document) вызывается ПОСЛЕ `await api.me()`.
 * frontend/js/motion.js:41 — каждой цели ставится data-reveal="out".
 * frontend/css/styles.css:190-198 — [data-reveal] { opacity: 0; transform: … }.
 *
 * Статическая разметка (.page-header, .card, .stat) отрисована браузером ещё на
 * этапе парсинга HTML и видна пользователю сразу. Через один сетевой обход
 * (100-800 мс на мобильной связи) скрипт вешает на неё data-reveal="out" —
 * содержимое исчезает и заново проявляется. Это ровно тот эффект, ради борьбы
 * с которым в layout.js:26-27 каркас рисуется из кэша.
 *
 * Полное визуальное подтверждение требует браузера; здесь доказывается
 * проверяемая часть: (1) до ответа сервера атрибута нет, (2) после ответа он
 * равен "out", (3) в CSS "out" означает opacity: 0.
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
  media: { '(min-width: 1024px)': true, '(max-width: 767px)': false },
});
globalThis.window.APP_CONFIG = APP_CONFIG;

const header = env.document.querySelector('.page-header');
const cards = env.document.querySelectorAll('.card');
let revealDuringRequest = null;

globalThis.fetch = makeFetch({
  '/auth/me/': () => {
    // момент «запрос ушёл, ответа ещё нет» — пользователь смотрит на страницу
    revealDuringRequest = header.dataset.reveal ?? null;
    return { status: 200, body: ME };
  },
});

const { initLayout } = await import(FRONTEND + 'js/layout.js');
await initLayout({ active: 'dashboard.html' });
await env.flush();

test('CSS: data-reveal="out" — это opacity: 0', () => {
  const block = css.match(/\[data-reveal\]\s*\{[^}]*\}/);
  assert.ok(block, 'правило [data-reveal] найдено');
  assert.match(block[0], /opacity:\s*0\s*;/, 'скрытие действительно через opacity: 0');
});

test('видимый .page-header гасится ответом сервера', () => {
  console.log('  data-reveal во время запроса:', revealDuringRequest);
  console.log('  data-reveal после ответа    :', header.dataset.reveal ?? null);
  assert.equal(revealDuringRequest, null, 'до ответа блок был видим (атрибута нет)');
  assert.notEqual(
    header.dataset.reveal,
    'out',
    'FAIL: после ответа сервера уже показанный заголовок страницы получил opacity: 0'
  );
});

test('то же самое происходит со всеми карточками панели', () => {
  const hidden = cards.filter((node) => node.dataset.reveal === 'out');
  console.log('  карточек погашено:', hidden.length, 'из', cards.length);
  assert.equal(hidden.length, 0, 'FAIL: содержимое панели скрыто уже после отрисовки');
});
