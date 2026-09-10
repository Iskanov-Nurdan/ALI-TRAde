/** Отчёты администратора: сводка за период и разрезы по расходам. */
import { api, downloadFile } from '../api.js';
import { initLayout } from '../layout.js';
import {
  clear,
  el,
  formatConverted,
  formatMoney,
  formatTotals,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  showApiError,
  toast,
} from '../ui.js';

const filtersForm = qs('#filters-form');
const summaryBox = qs('#summary');

let filters = {};

function collectFilters() {
  const data = Object.fromEntries(new FormData(filtersForm).entries());
  const result = {};
  Object.entries(data).forEach(([key, value]) => {
    const clean = String(value).trim();
    if (!clean) return;
    if (key === 'date_from') result[key] = `${clean}T00:00:00`;
    else if (key === 'date_to') result[key] = `${clean}T23:59:59`;
    else result[key] = clean;
  });
  return result;
}

function statCard(label, value, modifier, hint) {
  return el('article', { class: `stat ${modifier || ''}` }, [
    el('span', { class: 'stat__label', text: label }),
    el('strong', { class: 'stat__value', text: String(value) }),
    hint ? el('span', { class: 'stat__hint', text: hint }) : null,
  ]);
}

function renderTable(container, columns, rows, emptyTitle) {
  clear(container);
  if (!rows.length) {
    renderEmpty(container, emptyTitle);
    return;
  }
  container.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el(
            'tr',
            {},
            columns.map((column) =>
              el('th', { scope: 'col', class: column.numeric ? 'cell-num' : null, text: column.label })
            )
          ),
        ]),
        el(
          'tbody',
          {},
          rows.map((row) =>
            el(
              'tr',
              {},
              columns.map((column) =>
                el('td', { class: column.numeric ? 'cell-num' : null, text: column.value(row) })
              )
            )
          )
        ),
      ]),
    ])
  );
}

async function loadOptions() {
  const points = await api.listPoints({ page_size: 200 });
  ['#f-point-from', '#f-point-to'].forEach((selector) => {
    const select = qs(selector);
    clear(select).append(el('option', { value: '', text: 'Все' }));
    (points.results || points).forEach((point) => select.append(el('option', { value: point.id, text: point.name })));
  });
}

async function load() {
  renderLoading(summaryBox, 'Формируем отчёт…');
  ['#by-type', '#by-payer', '#by-vehicle', '#by-delivery', '#by-route', '#by-employee'].forEach((selector) =>
    renderLoading(qs(selector))
  );

  try {
    const [summary, expenses, employees] = await Promise.all([
      api.reportSummary(filters),
      api.reportExpenses(filters),
      api.reportEmployees(filters),
    ]);

    const stats = summary.summary;
    clear(summaryBox).append(
      statCard('Всего рейсов', stats.total, 'stat--primary'),
      statCard('В пути', stats.in_transit, 'stat--primary'),
      statCard('Просрочено', stats.overdue, 'stat--danger'),
      statCard('Прибыло', stats.arrived, 'stat--success'),
      statCard('С опозданием', stats.arrived_late, 'stat--warning'),
      statCard('Отменено', stats.cancelled),
      statCard('Записей расходов', stats.expenses_count, 'stat--warning'),
      statCard(
        'Сумма расходов',
        formatTotals(stats.expense_totals),
        'stat--warning',
        formatConverted(stats.expense_total_converted)
      )
    );

    renderTable(
      qs('#by-type'),
      [
        { label: 'Тип расхода', value: (row) => row.expense_type },
        { label: 'Сумма', numeric: true, value: (row) => formatMoney(row.total, row.currency) },
        { label: 'Записей', numeric: true, value: (row) => row.count },
      ],
      summary.by_expense_type,
      'Расходов за период нет'
    );

    renderTable(
      qs('#by-payer'),
      [
        { label: 'Плательщик', value: (row) => row.payer_display },
        { label: 'Сумма', numeric: true, value: (row) => formatMoney(row.total, row.currency) },
        { label: 'Записей', numeric: true, value: (row) => row.count },
      ],
      summary.by_payer,
      'Данных нет'
    );

    renderTable(
      qs('#by-vehicle'),
      [
        { label: 'Машина', value: (row) => row.vehicle_number },
        { label: 'Сумма', numeric: true, value: (row) => formatMoney(row.total, row.currency) },
        { label: 'Записей', numeric: true, value: (row) => row.count },
      ],
      expenses.by_vehicle,
      'Данных нет'
    );

    renderTable(
      qs('#by-delivery'),
      [
        { label: 'Рейс', value: (row) => `#${row.delivery_id}` },
        { label: 'Машина', value: (row) => row.vehicle_number },
        { label: 'Маршрут', value: (row) => row.route },
        { label: 'Сумма', numeric: true, value: (row) => formatMoney(row.total, row.currency) },
      ],
      expenses.by_delivery,
      'Данных нет'
    );

    renderTable(
      qs('#by-route'),
      [
        { label: 'Маршрут', value: (row) => row.route },
        { label: 'Рейсов', value: (row) => row.count },
        { label: 'Прибыло', value: (row) => row.arrived },
        { label: 'С опозданием', value: (row) => row.arrived_late },
      ],
      summary.by_route,
      'Рейсов за период нет'
    );

    renderTable(
      qs('#by-employee'),
      [
        { label: 'Сотрудник', value: (row) => row.full_name },
        { label: 'Отправил', value: (row) => row.dispatched },
        { label: 'Принял', value: (row) => row.received },
        { label: 'Расходов', value: (row) => row.expenses_count },
        { label: 'Сумма расходов', numeric: true, value: (row) => formatTotals(row.expense_totals) },
      ],
      employees.results,
      'Активности за период нет'
    );
  } catch (error) {
    renderError(summaryBox, error.message, load);
  }
}

(async () => {
  const user = await initLayout({ active: 'reports.html', adminOnly: true });
  if (!user) return;

  try {
    await loadOptions();
  } catch (error) {
    toast('Не удалось загрузить список точек.', 'error');
  }

  filtersForm.addEventListener('submit', (event) => {
    event.preventDefault();
    filters = collectFilters();
    load();
  });
  qs('#btn-reset').addEventListener('click', () => {
    setTimeout(() => {
      filters = {};
      load();
    }, 0);
  });

  qs('#export-deliveries').addEventListener('click', async () => {
    try {
      await downloadFile('/reports/export/deliveries/', filters, 'reisy.xlsx');
    } catch (error) {
      showApiError(error);
    }
  });
  qs('#export-expenses').addEventListener('click', async () => {
    try {
      await downloadFile('/reports/export/expenses/', filters, 'rashody.xlsx');
    } catch (error) {
      showApiError(error);
    }
  });

  await load();
})();
