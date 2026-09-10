/** Реестр расходов по всем рейсам с фильтрами и итогами по валютам. */
import { api, downloadFile } from '../api.js';
import { initLayout, isAdmin, queryParams, setQueryParams } from '../layout.js';
import {
  clear,
  el,
  formatDateTime,
  formatMoney,
  formatConverted,
  formatTotals,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  showApiError,
  toast,
  userName,
} from '../ui.js';

const listBox = qs('#expenses');
const totalsBox = qs('#totals');
const filtersForm = qs('#filters-form');
const pagination = qs('#pagination');

const state = { page: 1, pages: 1, filters: {} };

function collectFilters() {
  const data = Object.fromEntries(new FormData(filtersForm).entries());
  const filters = {};
  Object.entries(data).forEach(([key, value]) => {
    const clean = String(value).trim();
    if (!clean) return;
    if (key === 'date_from') filters[key] = `${clean}T00:00:00`;
    else if (key === 'date_to') filters[key] = `${clean}T23:59:59`;
    else filters[key] = clean;
  });
  return filters;
}

async function loadOptions() {
  const [types, dicts, employees] = await Promise.all([
    api.listExpenseTypes(),
    api.dictionaries(),
    api.employeeDirectory(),
  ]);

  const typeSelect = qs('#f-type');
  clear(typeSelect).append(el('option', { value: '', text: 'Все' }));
  (Array.isArray(types) ? types : types.results).forEach((type) =>
    typeSelect.append(el('option', { value: type.id, text: type.name }))
  );

  const payerSelect = qs('#f-payer');
  clear(payerSelect).append(el('option', { value: '', text: 'Все' }));
  dicts.payers.forEach((payer) => payerSelect.append(el('option', { value: payer.value, text: payer.label })));

  const currencySelect = qs('#f-currency');
  clear(currencySelect).append(el('option', { value: '', text: 'Все' }));
  dicts.currencies.forEach((currency) => currencySelect.append(el('option', { value: currency.value, text: currency.value })));

  const authorSelect = qs('#f-author');
  clear(authorSelect).append(el('option', { value: '', text: 'Все' }));
  employees.forEach((user) => authorSelect.append(el('option', { value: user.id, text: user.full_name })));
}

function renderTable(expenses) {
  clear(listBox);
  if (!expenses.length) {
    renderEmpty(listBox, 'Расходов не найдено', 'Измените условия фильтра.');
    return;
  }

  const rows = expenses.map((expense) =>
    el('tr', {}, [
      el('td', {}, [
        el('a', { class: 'cell-strong', href: `delivery.html?id=${expense.delivery}`, text: expense.delivery_vehicle }),
        el('div', { class: 'cell-muted', text: `Рейс #${expense.delivery}` }),
      ]),
      el('td', { text: expense.expense_type_name }),
      el('td', { class: 'cell-num cell-strong', text: formatMoney(expense.amount, expense.currency) }),
      el('td', { text: expense.payer_display }),
      el('td', {}, [
        el('div', { text: expense.description }),
        expense.comment ? el('div', { class: 'cell-muted', text: expense.comment }) : null,
      ]),
      el('td', { text: userName(expense.created_by) }),
      el('td', { class: 'cell-nowrap', text: formatDateTime(expense.created_at) }),
    ])
  );

  listBox.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el(
            'tr',
            {},
            ['Машина', 'Тип', 'Сумма', 'Плательщик', 'Описание', 'Добавил', 'Дата'].map((label) =>
              el('th', { scope: 'col', class: label === 'Сумма' ? 'cell-num' : null, text: label })
            )
          ),
        ]),
        el('tbody', {}, rows),
      ]),
    ])
  );
}

async function loadExpenses() {
  renderLoading(listBox);
  pagination.hidden = true;
  try {
    const params = { ...state.filters, page: state.page, page_size: 25 };
    const [data, totals] = await Promise.all([api.listExpenses(params), api.expenseTotals(state.filters)]);

    state.pages = data.pages || 1;
    renderTable(data.results);
    const converted = formatConverted(totals.converted);
    totalsBox.textContent =
      `Итого: ${formatTotals(totals.totals)}${converted ? ` ${converted}` : ''} · записей ${totals.count}`;

    qs('#page-info').textContent = `Страница ${data.page} из ${data.pages}`;
    qs('#page-prev').disabled = data.page <= 1;
    qs('#page-next').disabled = data.page >= data.pages;
    pagination.hidden = data.pages <= 1;
  } catch (error) {
    renderError(listBox, error.message, loadExpenses);
  }
}

(async () => {
  const user = await initLayout({ active: 'expenses.html' });
  if (!user) return;

  try {
    await loadOptions();
  } catch (error) {
    toast('Не удалось загрузить справочники.', 'error');
  }

  const params = queryParams();
  Object.entries(params).forEach(([key, value]) => {
    const input = filtersForm.elements[key];
    if (input) input.value = value;
  });
  state.filters = collectFilters();

  if (isAdmin()) {
    const exportBtn = qs('#btn-export');
    exportBtn.hidden = false;
    exportBtn.addEventListener('click', async () => {
      try {
        await downloadFile('/reports/export/expenses/', state.filters, 'rashody.xlsx');
      } catch (error) {
        showApiError(error);
      }
    });
  }

  filtersForm.addEventListener('submit', (event) => {
    event.preventDefault();
    state.filters = collectFilters();
    state.page = 1;
    setQueryParams(Object.fromEntries(new FormData(filtersForm).entries()));
    loadExpenses();
  });

  qs('#btn-reset').addEventListener('click', () => {
    setTimeout(() => {
      state.filters = {};
      state.page = 1;
      setQueryParams({});
      loadExpenses();
    }, 0);
  });

  qs('#page-prev').addEventListener('click', () => {
    if (state.page > 1) {
      state.page -= 1;
      loadExpenses();
    }
  });
  qs('#page-next').addEventListener('click', () => {
    if (state.page < state.pages) {
      state.page += 1;
      loadExpenses();
    }
  });

  await loadExpenses();
})();
