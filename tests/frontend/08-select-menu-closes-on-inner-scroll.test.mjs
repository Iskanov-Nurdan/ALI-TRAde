/**
 * Длинный выпадающий список нельзя прокрутить: он закрывается.
 *
 * frontend/js/components/select.js — меню закрепляется position: fixed рядом с
 * кнопкой, поэтому при прокрутке страницы его закрывают, иначе оно повиснет в
 * отрыве от кнопки. Обработчик вешался на window в фазе перехвата:
 *
 *     window.addEventListener('scroll', close, true);
 *
 * Перехват доставляет и события прокрутки внутри самого меню — а у него
 * max-height: 260px и собственная полоса. На странице «Новый рейс» точек
 * отправления больше, чем помещается: первое же движение колеса закрывало
 * список, и выбрать дальние пункты («Термис», «Наманган») было нельзя.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { APP_CONFIG } from './helpers/net.mjs';

const html = fs.readFileSync(fileURLToPath(FRONTEND + 'deliveries.html'), 'utf8');
const env = installDom({ html, media: { '(max-width: 767px)': false } });
globalThis.window.APP_CONFIG = APP_CONFIG;

const { enhanceSelect } = await import(FRONTEND + 'js/components/select.js');

/** Список точек, который не помещается в 260px меню. */
function selectWithManyOptions(doc) {
  const select = doc.createElement('select');
  ['— выберите точку —', 'Адижан', 'Афганистана', 'Достук', 'Кара-Тай', 'Наманган', 'Термис']
    .forEach((name, index) => {
      const option = doc.createElement('option');
      option.value = index ? String(index) : '';
      option.textContent = name;
      select.append(option);
    });
  doc.body.append(select);
  enhanceSelect(select);
  return select;
}

function openMenuFor(select, doc) {
  const button = select.closest('.select').querySelector('.select__button');
  button.dispatchEvent(new globalThis.Event('click', { bubbles: true }));
  return { button, menu: doc.querySelector('.select__menu') };
}

test('прокрутка внутри списка его не закрывает', () => {
  const doc = env.document;
  const select = selectWithManyOptions(doc);
  const { menu } = openMenuFor(select, doc);

  assert.ok(menu, 'меню открылось');
  assert.equal(menu.hidden, false);

  // Колесо над списком: браузер шлёт scroll с target = сам список.
  const event = new globalThis.Event('scroll');
  event.target = menu;
  globalThis.window.dispatchEvent(event);

  assert.equal(menu.hidden, false, 'список остался открыт');
  assert.ok(doc.querySelector('.select__menu'), 'список остался в документе');

  // И пункты по-прежнему на месте — есть что выбирать
  assert.equal(menu.querySelectorAll('.select__option').length, 7);
});

test('прокрутка внутри пункта списка тоже не закрывает', () => {
  const doc = env.document;
  const select = selectWithManyOptions(doc);
  const { menu } = openMenuFor(select, doc);

  const event = new globalThis.Event('scroll');
  event.target = menu.querySelector('.select__option');
  globalThis.window.dispatchEvent(event);

  assert.equal(menu.hidden, false, 'вложенный target не закрывает список');
});

test('прокрутка страницы список закрывает', () => {
  const doc = env.document;
  const select = selectWithManyOptions(doc);
  const { menu } = openMenuFor(select, doc);

  const event = new globalThis.Event('scroll');
  event.target = doc; // прокрутился документ, меню уехало от кнопки
  globalThis.window.dispatchEvent(event);

  assert.equal(menu.hidden, true, 'список закрыт');
  assert.equal(doc.querySelector('.select__menu'), null, 'и убран из документа');
});
