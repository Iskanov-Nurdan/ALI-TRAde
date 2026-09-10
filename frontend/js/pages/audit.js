/** Журнал аудита: кто и что менял в системе. */
import { api } from '../api.js';
import { initLayout } from '../layout.js';
import {
  clear,
  el,
  formatDateTime,
  qs,
  renderEmpty,
  renderError,
  renderLoading,
  toast,
  userName,
} from '../ui.js';

const listBox = qs('#audit');
const filtersForm = qs('#filters-form');
const pagination = qs('#pagination');
const state = { page: 1, pages: 1, filters: {} };

const ENTITY_LABELS = {
  delivery: 'Рейс',
  delivery_waypoint: 'Точка маршрута',
  expense: 'Расход',
  expense_type: 'Тип расхода',
  expense_settings: 'Настройки расходов',
  currency_rate: 'Курс валюты',
  point: 'Точка',
  user: 'Сотрудник',
};

/** Названия полей так, как их видит сотрудник, а не как они зовутся в базе. */
const FIELD_LABELS = {
  full_name: 'ФИО',
  login: 'Логин',
  phone: 'Телефон',
  role: 'Роль',
  is_active: 'Активен',
  name: 'Название',
  code: 'Код',
  address: 'Адрес',
  description: 'Описание',
  comment: 'Комментарий',
  sort_order: 'Порядок',
  vehicle_number: 'Машина',
  point_from: 'Откуда',
  point_to: 'Куда',
  route: 'Маршрут',
  status: 'Статус',
  dispatched_at: 'Отправлена',
  deadline_at: 'Дедлайн',
  received_at: 'Прибыла',
  passed_at: 'Пройдена',
  late_minutes: 'Опоздание',
  expenses_count: 'Расходов',
  events_count: 'Событий',
  delivery_id: 'Рейс',
  type: 'Тип',
  amount: 'Сумма',
  currency: 'Валюта',
  payer: 'Плательщик',
  created_by: 'Добавил',
  point: 'Точка',
  reason: 'Причина',
  rate: 'Курс',
  auto_payer_enabled: 'Правило плательщика',
  threshold_amount: 'Порог суммы',
  threshold_currency: 'Валюта порога',
  payer_above: 'Плательщик свыше порога',
  payer_below: 'Плательщик по умолчанию',
};

/** Служебные коды в человеческие названия. */
const VALUE_LABELS = {
  ADMIN: 'Администратор',
  EMPLOYEE: 'Сотрудник',
  CREATED: 'Создан',
  IN_TRANSIT: 'В пути',
  ARRIVED: 'Прибыл',
  CANCELLED: 'Отменён',
  COMPANY: 'Наша компания',
  CHINA: 'Китай',
  DRIVER: 'Водитель',
  OTHER: 'Другое',
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function formatItem(value) {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'string') {
    if (VALUE_LABELS[value]) return VALUE_LABELS[value];
    if (ISO_DATE.test(value)) return formatDateTime(value);
    return value;
  }
  if (typeof value === 'object') {
    // Курсы валют приходят парой «было/стало»
    if ('было' in value && 'стало' in value) return `${value['было']} → ${value['стало']}`;
    return Object.entries(value)
      .map(([key, item]) => `${FIELD_LABELS[key] || key}: ${formatItem(item)}`)
      .join(', ');
  }
  return String(value);
}

function formatValue(value) {
  if (!value || typeof value !== 'object') return '—';
  const parts = Object.entries(value).map(([key, item]) => {
    const label = FIELD_LABELS[key] || key;
    return `${label}: ${formatItem(item)}`;
  });
  return parts.length ? parts.join(' · ') : '—';
}

function renderTable(entries) {
  clear(listBox);
  if (!entries.length) {
    renderEmpty(listBox, 'Записей нет');
    return;
  }

  const rows = entries.map((entry) =>
    el('tr', {}, [
      el('td', { class: 'cell-nowrap', text: formatDateTime(entry.created_at) }),
      el('td', { text: userName(entry.user) }),
      el('td', { text: entry.action_display }),
      el('td', {}, [
        el('div', { text: ENTITY_LABELS[entry.entity_type] || entry.entity_type }),
        el('div', {
          class: 'cell-muted',
          text: entry.entity_id === 'all' ? 'все записи' : `#${entry.entity_id}`,
        }),
      ]),
      el('td', { class: 'cell-muted', text: formatValue(entry.old_value) }),
      el('td', { class: 'cell-muted', text: formatValue(entry.new_value) }),
    ])
  );

  listBox.append(
    el('div', { class: 'table-wrapper' }, [
      el('table', {}, [
        el('thead', {}, [
          el('tr', {}, ['Дата', 'Сотрудник', 'Действие', 'Объект', 'Было', 'Стало'].map((label) => el('th', { scope: 'col', text: label }))),
        ]),
        el('tbody', {}, rows),
      ]),
    ])
  );
}

async function load() {
  renderLoading(listBox);
  pagination.hidden = true;
  try {
    const data = await api.listAudit({ ...state.filters, page: state.page, page_size: 50 });
    state.pages = data.pages || 1;
    renderTable(data.results);
    qs('#list-count').textContent = `Всего: ${data.count}`;
    qs('#page-info').textContent = `Страница ${data.page} из ${data.pages}`;
    qs('#page-prev').disabled = data.page <= 1;
    qs('#page-next').disabled = data.page >= data.pages;
    pagination.hidden = data.pages <= 1;
  } catch (error) {
    renderError(listBox, error.message, load);
  }
}

(async () => {
  const user = await initLayout({ active: 'audit.html', adminOnly: true });
  if (!user) return;

  try {
    const employees = await api.employeeDirectory();
    const select = qs('#f-user');
    clear(select).append(el('option', { value: '', text: 'Все' }));
    employees.forEach((item) => select.append(el('option', { value: item.id, text: item.full_name })));
  } catch (error) {
    toast('Не удалось загрузить список сотрудников.', 'error');
  }

  filtersForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(filtersForm).entries());
    state.filters = Object.fromEntries(Object.entries(data).filter(([, value]) => String(value).trim()));
    state.page = 1;
    load();
  });

  qs('#btn-reset').addEventListener('click', () => {
    setTimeout(() => {
      state.filters = {};
      state.page = 1;
      load();
    }, 0);
  });

  qs('#page-prev').addEventListener('click', () => {
    if (state.page > 1) {
      state.page -= 1;
      load();
    }
  });
  qs('#page-next').addEventListener('click', () => {
    if (state.page < state.pages) {
      state.page += 1;
      load();
    }
  });

  await load();
})();
