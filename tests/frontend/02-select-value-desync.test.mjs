/**
 * АТАКА 2. Кастомный <select> рассинхронизируется с реальным значением.
 *
 * frontend/js/components/select.js:135-136 — подпись кнопки (syncLabel) обновляется
 * только по событию `change` и по MutationObserver({childList, subtree, attributes}).
 * Программное присваивание `select.value = 'x'` в браузере не меняет ни одного
 * атрибута и не шлёт `change` — значит syncLabel не вызывается.
 *
 * Такое присваивание есть в рабочих сценариях:
 *   frontend/js/pages/deliveries.js:52  applyFiltersToForm() — восстановление фильтров из адреса
 *   frontend/js/pages/expenses.js:144   то же самое
 *   frontend/js/pages/users.js:111      form.elements.role.value = user.role (карточка сотрудника)
 *
 * Переход по ссылке с dashboard.html «Просроченные» (dashboard.html:62 ->
 * deliveries.html?state=overdue) заполняет #f-state значением overdue, но
 * видимый выпадающий список продолжает показывать «Все»: список отфильтрован,
 * а элемент управления врёт. Нажатие «Применить» отправит форму как есть —
 * значение уцелеет, но пользователь видит не то, что применено.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { installDom, FRONTEND } from './helpers/mini-dom.mjs';
import { APP_CONFIG } from './helpers/net.mjs';

const deliveriesHtml = fs.readFileSync(fileURLToPath(FRONTEND + 'deliveries.html'), 'utf8');
const env = installDom({ html: deliveriesHtml, media: { '(max-width: 767px)': false } });
globalThis.window.APP_CONFIG = APP_CONFIG;

const { enhanceSelects } = await import(FRONTEND + 'js/components/select.js');

test('deliveries.html?state=overdue: список отфильтрован, а выпадающий список показывает «Все»', async () => {
  const doc = env.document;
  enhanceSelects(doc);
  await env.flush();

  const form = doc.querySelector('#filters-form');
  const select = doc.querySelector('#f-state');
  const label = select.closest('.select').querySelector('.select__label');

  assert.equal(label.textContent, 'Все', 'до подстановки подпись — «Все»');

  // ровно то, что делает applyFiltersToForm в js/pages/deliveries.js:49-54
  Object.entries({ state: 'overdue' }).forEach(([key, value]) => {
    const input = form.elements[key];
    if (input) input.value = value;
  });
  await env.flush();

  console.log('  select.value      =', select.value);
  console.log('  видимая подпись   =', JSON.stringify(label.textContent));

  assert.equal(select.value, 'overdue', 'значение действительно проставлено');
  assert.equal(
    label.textContent,
    'Просроченные',
    'FAIL: кнопка выпадающего списка показывает старую подпись — интерфейс врёт о применённом фильтре'
  );
});

test('users.html: редактирование администратора показывает роль «Сотрудник»', async () => {
  const usersHtml = fs.readFileSync(fileURLToPath(FRONTEND + 'users.html'), 'utf8');
  const usersEnv = installDom({ html: usersHtml, media: { '(max-width: 767px)': false } });
  const doc = usersEnv.document;
  enhanceSelects(doc);
  await usersEnv.flush();

  const form = doc.querySelector('#user-form');
  const select = doc.querySelector('#u-role');
  const label = select.closest('.select').querySelector('.select__label');

  // js/pages/users.js:111 — openEdit()
  form.elements.role.value = 'ADMIN';
  await usersEnv.flush();

  console.log('  select.value    =', select.value);
  console.log('  видимая подпись =', JSON.stringify(label.textContent));

  assert.equal(select.value, 'ADMIN');
  assert.equal(
    label.textContent,
    'Администратор',
    'FAIL: в карточке администратора роль отображается как «Сотрудник»'
  );
});

test('КОНТРОЛЬ: событие change подпись обновляет — сломано именно программное присваивание', async () => {
  const doc = env.document;
  const select = doc.querySelector('#f-state');
  const label = select.closest('.select').querySelector('.select__label');
  select.value = 'arrived';
  select.dispatchEvent(new Event('change', { bubbles: true }));
  assert.equal(label.textContent, 'Прибывшие');
});
