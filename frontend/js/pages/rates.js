/** Курсы валют к сому: просмотр всеми, изменение администратором. */
import { api } from '../api.js';
import { initLayout, isAdmin } from '../layout.js';
import {
  clear,
  el,
  formatDateTime,
  formatMoney,
  qs,
  renderError,
  renderLoading,
  showApiError,
  toast,
  userName,
} from '../ui.js';

const listBox = qs('#rates');
const calcForm = qs('#calc-form');

let rates = [];
let base = 'KGS';

function renderTable() {
  clear(listBox);

  const rows = rates.map((item) => {
    const input = el('input', {
      type: 'number',
      min: '0.0001',
      step: '0.0001',
      value: item.rate,
      name: item.code,
      disabled: item.is_base || !isAdmin(),
      'aria-label': `Курс ${item.code} к сому`,
    });
    input.addEventListener('input', updateCalc);

    return el('tr', {}, [
      el('td', {}, [
        el('div', { class: 'cell-strong', text: item.code }),
        el('div', { class: 'cell-muted', text: item.currency_display }),
      ]),
      el('td', {}, [
        item.is_base
          ? el('span', { class: 'badge badge--primary', text: 'Базовая валюта' })
          : el('div', { class: 'rate-input' }, [input, el('span', { class: 'cell-muted', text: 'сом' })]),
      ]),
      el('td', { class: 'cell-muted', text: item.updated_by ? userName(item.updated_by) : '—' }),
      el('td', { class: 'cell-nowrap cell-muted', text: item.updated_at ? formatDateTime(item.updated_at) : '—' }),
    ]);
  });

  listBox.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el('tr', {}, ['Валюта', `Курс к ${base}`, 'Обновил', 'Обновлено'].map((label) =>
            el('th', { scope: 'col', text: label })
          )),
        ]),
        el('tbody', {}, rows),
      ]),
    ])
  );
}

function fillCurrencies() {
  const select = qs('#calc-currency');
  clear(select);
  rates.forEach((item) => select.append(el('option', { value: item.code, text: `${item.code} — ${item.currency_display}` })));
  select.value = rates.some((item) => item.code === 'USD') ? 'USD' : base;
}

function currentRate(code) {
  const input = listBox.querySelector(`input[name="${code}"]`);
  if (input) return Number(input.value) || 0;
  const item = rates.find((rate) => rate.code === code);
  return item ? Number(item.rate) : 0;
}

function updateCalc() {
  const amount = Number(qs('#calc-amount').value) || 0;
  const code = qs('#calc-currency').value;
  const result = amount * currentRate(code);
  qs('#calc-result').textContent = amount ? formatMoney(result, base) : '—';
}

async function load() {
  renderLoading(listBox);
  try {
    const data = await api.currencyRates();
    rates = data.results;
    base = data.base || 'KGS';
    renderTable();
    fillCurrencies();
    updateCalc();

    const updated = rates
      .filter((item) => item.updated_by)
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))[0];
    qs('#updated-info').textContent = updated
      ? `Последнее изменение: ${formatDateTime(updated.updated_at)}, ${userName(updated.updated_by)}`
      : 'Курсы ещё не изменяли';
  } catch (error) {
    renderError(listBox, error.message, load);
  }
}

async function save() {
  const button = qs('#btn-save');
  const payload = {};
  rates
    .filter((item) => !item.is_base)
    .forEach((item) => {
      const value = currentRate(item.code);
      if (value > 0) payload[item.code] = String(value);
    });

  if (!Object.keys(payload).length) {
    toast('Нет курсов для сохранения.', 'error');
    return;
  }

  button.disabled = true;
  try {
    const data = await api.updateCurrencyRates({ rates: payload });
    rates = data.results;
    renderTable();
    updateCalc();
    toast('Курсы сохранены.', 'success');
  } catch (error) {
    showApiError(error);
  } finally {
    button.disabled = false;
  }
}

(async () => {
  const user = await initLayout({ active: 'rates.html' });
  if (!user) return;

  const saveButton = qs('#btn-save');
  if (isAdmin()) saveButton.addEventListener('click', save);
  else saveButton.hidden = true;

  calcForm.addEventListener('submit', (event) => event.preventDefault());
  qs('#calc-amount').addEventListener('input', updateCalc);
  qs('#calc-currency').addEventListener('change', updateCalc);

  await load();
})();
