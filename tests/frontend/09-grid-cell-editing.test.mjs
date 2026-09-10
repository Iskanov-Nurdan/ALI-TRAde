/**
 * Таблица с правкой в ячейках (frontend/js/components/grid.js).
 *
 * Проверяется то, на чём такие сетки обычно и ломаются:
 *  - правка уходит на сервер один раз и только изменённым полем;
 *  - Escape отменяет ввод, а не сохраняет его;
 *  - колонки только для чтения не редактируются вовсе — иначе через таблицу
 *    можно было бы менять статус рейса в обход истории и журнала действий;
 *  - отказ сервера возвращает прежнее значение, а не оставляет в ячейке то,
 *    что на самом деле не сохранилось.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';

const html = fs.readFileSync(fileURLToPath(FRONTEND + 'deliveries.html'), 'utf8');
const env = installDom({ html, media: { '(max-width: 767px)': false } });

const { createGrid } = await import(FRONTEND + 'js/components/grid.js');

const COLUMNS = [
  { key: 'vehicle_number', title: 'Номер машины', type: 'text' },
  { key: 'status', title: 'Статус', type: 'readonly' },
];

function buildGrid({ onSave = async () => {}, readOnly = false } = {}) {
  const host = env.document.createElement('div');
  env.document.body.append(host);
  const rows = [
    { id: 1, vehicle_number: '01 KG 111 AB', status: 'В пути' },
    { id: 2, vehicle_number: '02 KG 222 CD', status: 'Прибыл' },
  ];
  const grid = createGrid(host, {
    columns: COLUMNS,
    rows,
    rowKey: (row) => row.id,
    readOnly,
    onSave,
  });
  return { host, grid, rows };
}

const cell = (host, row, col) => host.querySelector(`td[data-row="${row}"][data-col="${col}"]`);
const keydown = (node, key, extra = {}) => {
  const event = new globalThis.Event('keydown', { bubbles: true });
  Object.assign(event, { key, ...extra });
  node.dispatchEvent(event);
  return event;
};

test('правка ячейки уходит на сервер одним полем', async () => {
  const calls = [];
  const { host } = buildGrid({
    onSave: async (row, column, value) => {
      calls.push({ id: row.id, key: column.key, value });
      return { vehicle_number: value };
    },
  });

  const target = cell(host, 0, 0);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));

  const input = target.querySelector('input');
  assert.ok(input, 'ячейка перешла в режим ввода');
  assert.equal(input.value, '01 KG 111 AB', 'в поле подставлено текущее значение');

  input.value = '03 KG 333 EF';
  keydown(input, 'Enter');
  await env.flush();

  assert.equal(calls.length, 1, 'ровно один запрос на сохранение');
  assert.deepEqual(calls[0], { id: 1, key: 'vehicle_number', value: '03 KG 333 EF' });
  assert.equal(target.textContent, '03 KG 333 EF', 'в ячейке — сохранённое значение');
});

test('значение не изменилось — запроса нет', async () => {
  const calls = [];
  const { host } = buildGrid({ onSave: async () => calls.push(1) });

  const target = cell(host, 0, 0);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));
  keydown(target.querySelector('input'), 'Enter');
  await env.flush();

  assert.equal(calls.length, 0, 'лишний PATCH не отправляется');
});

test('Escape отменяет правку', async () => {
  const calls = [];
  const { host } = buildGrid({ onSave: async () => calls.push(1) });

  const target = cell(host, 0, 0);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));
  const input = target.querySelector('input');
  input.value = 'ерунда';
  keydown(input, 'Escape');
  await env.flush();

  assert.equal(calls.length, 0, 'ничего не сохранено');
  assert.equal(target.textContent, '01 KG 111 AB', 'вернулось прежнее значение');
});

test('колонка только для чтения не редактируется', async () => {
  const calls = [];
  const { host } = buildGrid({ onSave: async () => calls.push(1) });

  const target = cell(host, 0, 1);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));
  await env.flush();

  assert.equal(target.querySelector('input'), null, 'поле ввода не появилось');
  assert.ok(target.classList.contains('grid__cell--locked'), 'ячейка помечена как закрытая');
  assert.equal(calls.length, 0);
});

test('сотруднику без прав таблица открыта только на чтение', async () => {
  const { host } = buildGrid({ readOnly: true });

  const target = cell(host, 0, 0);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));
  await env.flush();

  assert.equal(target.querySelector('input'), null, 'правка недоступна');
});

test('отказ сервера возвращает прежнее значение', async () => {
  const { host } = buildGrid({
    onSave: async () => {
      throw new Error('403');
    },
  });

  const target = cell(host, 0, 0);
  target.dispatchEvent(new globalThis.Event('dblclick', { bubbles: true }));
  const input = target.querySelector('input');
  input.value = 'не сохранится';
  keydown(input, 'Enter');
  await env.flush();

  assert.equal(
    target.textContent,
    '01 KG 111 AB',
    'в ячейке не остаётся значение, которого нет на сервере'
  );
});
