/**
 * Таблица рейсов с правкой в ячейках — привычный по Google Таблицам вид.
 *
 * Смена состояния рейса (отправлен, принят, отменён) сюда намеренно не входит:
 * такие действия пишутся в историю рейса и делаются на его карточке. Здесь
 * правятся только данные, которые принимает PATCH /api/deliveries/{id}/.
 */
import { api } from '../api.js';
import { initLayout, isAdmin, queryParams } from '../layout.js';
import { createGrid } from '../components/grid.js';
import {
  formatConverted,
  formatDateTime,
  fromLocalInputValue,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  showApiError,
  toLocalInputValue,
  toast,
  userName,
} from '../ui.js';

const PAGE_SIZE = 100;

const box = qs('#sheet');
const statusLine = qs('#sheet-status');
const moreButton = qs('#sheet-more');
const stateSelect = qs('#sheet-state');

let grid = null;
let points = [];
let nextPage = 1;
let hasMore = false;

/** Значение для input[type=datetime-local] из ответа API. */
const toInput = (value) => (value ? toLocalInputValue(new Date(value)) : '');

const STATE_LABELS = {
  CREATED: 'Создан',
  IN_TRANSIT: 'В пути',
  ARRIVED: 'Прибыл',
  CANCELLED: 'Отменён',
};

function buildColumns() {
  const pointOptions = [
    { value: '', label: '— не выбрано —' },
    ...points.map((point) => ({ value: point.id, label: point.name })),
  ];

  return [
    {
      key: 'vehicle_number',
      title: 'Номер машины',
      width: 150,
      type: 'text',
      toPayload: (value) => ({ vehicle_number: value }),
    },
    {
      key: 'point_from',
      title: 'Откуда',
      width: 150,
      type: 'select',
      options: pointOptions,
      editValue: (row) => row.point_from?.id ?? '',
      format: (value) => value?.name ?? '',
      toPayload: (value) => ({ point_from_id: Number(value) }),
    },
    {
      key: 'point_to',
      title: 'Куда',
      width: 150,
      type: 'select',
      options: pointOptions,
      editValue: (row) => row.point_to?.id ?? '',
      format: (value) => value?.name ?? '',
      toPayload: (value) => ({ point_to_id: Number(value) }),
    },
    {
      key: 'dispatched_at',
      title: 'Отправление',
      width: 165,
      type: 'datetime',
      editValue: (row) => toInput(row.dispatched_at),
      format: (value) => formatDateTime(value),
      toPayload: (value) => ({ dispatched_at: fromLocalInputValue(value) }),
    },
    {
      key: 'deadline_at',
      title: 'План прибытия',
      width: 165,
      type: 'datetime',
      editValue: (row) => toInput(row.deadline_at),
      format: (value) => formatDateTime(value),
      toPayload: (value) => ({ deadline_at: fromLocalInputValue(value) }),
    },
    {
      key: 'received_at',
      title: 'Факт прибытия',
      width: 165,
      type: 'readonly',
      format: (value) => formatDateTime(value),
    },
    {
      key: 'status',
      title: 'Статус',
      width: 120,
      type: 'readonly',
      format: (value, row) => (row.is_overdue ? 'Просрочен' : STATE_LABELS[value] || value),
    },
    {
      key: 'expense_total_converted',
      title: 'Расходы',
      width: 120,
      type: 'readonly',
      align: 'right',
      format: (value) => formatConverted(value),
    },
    {
      key: 'created_by',
      title: 'Создал',
      width: 160,
      type: 'readonly',
      format: (value) => userName(value),
    },
  ];
}

/** Цвет строки: просрочка и наличие расходов — как в списке рейсов. */
function rowClassFor(row) {
  if (row.color === 'RED') return 'table-row--red';
  if (row.color === 'ORANGE') return 'table-row--orange';
  return '';
}

async function saveCell(row, column, value) {
  if (!column.toPayload) return;
  const payload = column.toPayload(value);
  try {
    const updated = await api.updateDelivery(row.id, payload);
    return updated;
  } catch (error) {
    showApiError(error);
    throw error;
  }
}

function updateStatusLine(total) {
  const count = grid ? grid.rows.length : 0;
  statusLine.textContent = isAdmin()
    ? `Показано ${count} из ${total}. Правьте прямо в ячейках: Enter — изменить, Escape — отменить.`
    : `Показано ${count} из ${total}. Изменение рейсов доступно администратору.`;
  moreButton.hidden = !hasMore;
}

async function load({ append = false } = {}) {
  const params = { page: nextPage, page_size: PAGE_SIZE };
  const state = stateSelect.value;
  if (state) params.state = state;

  if (!append) renderLoading(box, 'Загрузка рейсов…');

  try {
    const response = await api.listDeliveries(params);
    const rows = response.results || response;
    const total = response.count ?? rows.length;
    // Пагинация отдаёт page/pages, ссылки next в ответе нет.
    hasMore = Boolean(response.pages) && response.page < response.pages;
    nextPage = (response.page ?? nextPage) + 1;

    if (!rows.length && !append) {
      renderEmpty(box, 'Рейсов нет', 'Измените фильтр или создайте рейс на странице «Рейсы».');
      statusLine.textContent = '';
      moreButton.hidden = true;
      return;
    }

    if (append && grid) {
      grid.appendRows(rows);
    } else {
      grid = createGrid(box, {
        columns: buildColumns(),
        rows,
        rowKey: (row) => row.id,
        rowClass: rowClassFor,
        readOnly: !isAdmin(),
        onSave: saveCell,
      });
    }
    updateStatusLine(total);
  } catch (error) {
    renderError(box, 'Не удалось загрузить рейсы', () => {
      nextPage = 1;
      load();
    });
    showApiError(error);
  }
}

async function init() {
  await initLayout({ active: 'sheet.html' });

  try {
    const response = await api.listPoints({ page_size: 200, is_active: true });
    points = response.results || response;
  } catch (error) {
    // Без точек таблица всё равно работает: колонки со списками останутся
    // пустыми, а остальные поля правятся как обычно.
    toast('Не удалось загрузить точки — списки будут пустыми', 'error');
  }

  const params = queryParams();
  if (params.state) stateSelect.value = params.state;

  stateSelect.addEventListener('change', () => {
    nextPage = 1;
    load();
  });
  moreButton.addEventListener('click', () => load({ append: true }));

  await load();
}

init();
