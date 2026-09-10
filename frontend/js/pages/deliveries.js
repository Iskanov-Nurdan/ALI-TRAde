/** Список рейсов: фильтры, пагинация, создание рейса. */
import { api, downloadFile } from '../api.js';
import { initLayout, isAdmin, queryParams, setQueryParams } from '../layout.js';
import {
  clear,
  el,
  formatDateTime,
  fromLocalInputValue,
  openModal,
  closeModal,
  qs,
  renderError,
  renderLoading,
  setupModal,
  showApiError,
  toast,
  toLocalInputValue,
} from '../ui.js';
import { renderDeliveryTable } from '../components/delivery-table.js';
import { icon, hydrateIcons } from '../icons.js';

const listBox = qs('#deliveries');
const countBox = qs('#list-count');
const filtersForm = qs('#filters-form');
const pagination = qs('#pagination');
const pageInfo = qs('#page-info');
const modal = setupModal(qs('#delivery-modal'));
const deliveryForm = qs('#delivery-form');

const state = { page: 1, pages: 1, filters: {} };
/** Выбранные промежуточные точки в порядке прохождения: [{id, name}]. */
let waypoints = [];
let allPoints = [];

function collectFilters() {
  const data = Object.fromEntries(new FormData(filtersForm).entries());
  const filters = {};
  Object.entries(data).forEach(([key, value]) => {
    const clean = String(value).trim();
    if (!clean) return;
    // Даты приходят как YYYY-MM-DD — расширяем до границ суток.
    if (key === 'date_from') filters[key] = `${clean}T00:00:00`;
    else if (key === 'date_to') filters[key] = `${clean}T23:59:59`;
    else filters[key] = clean;
  });
  return filters;
}

function applyFiltersToForm(params) {
  Object.entries(params).forEach(([key, value]) => {
    const input = filtersForm.elements[key];
    if (input) input.value = value;
  });
}

async function loadOptions() {
  const [points, employees] = await Promise.all([
    api.listPoints({ page_size: 200, is_active: true }),
    api.employeeDirectory(),
  ]);

  const pointOptions = points.results || points;
  ['#f-point-from', '#f-point-to'].forEach((selector) => {
    const select = qs(selector);
    clear(select).append(el('option', { value: '', text: 'Все' }));
    pointOptions.forEach((point) => select.append(el('option', { value: point.id, text: point.name })));
  });
  allPoints = pointOptions;

  ['#d-point-from', '#d-point-to'].forEach((selector) => {
    const select = qs(selector);
    clear(select).append(el('option', { value: '', text: '— выберите точку —' }));
    pointOptions.forEach((point) => select.append(el('option', { value: point.id, text: point.name })));
  });

  ['#f-dispatched-by', '#f-received-by'].forEach((selector) => {
    const select = qs(selector);
    clear(select).append(el('option', { value: '', text: 'Все' }));
    employees.forEach((user) => select.append(el('option', { value: user.id, text: user.full_name })));
  });
}

async function loadDeliveries() {
  renderLoading(listBox);
  pagination.hidden = true;

  try {
    const params = { ...state.filters, page: state.page, page_size: 25 };
    const data = await api.listDeliveries(params);
    state.pages = data.pages || 1;

    renderDeliveryTable(listBox, data.results, {
      emptyTitle: 'Рейсы не найдены',
      emptyHint: 'Измените условия фильтра или создайте новый рейс.',
    });

    countBox.textContent = `Найдено: ${data.count}`;
    pageInfo.textContent = `Страница ${data.page} из ${data.pages}`;
    qs('#page-prev').disabled = data.page <= 1;
    qs('#page-next').disabled = data.page >= data.pages;
    pagination.hidden = data.pages <= 1;
  } catch (error) {
    renderError(listBox, error.message, loadDeliveries);
  }
}

/* ----------------------- Маршрут с промежуточными точками ---------------- */

/** Точки, которые ещё можно добавить: не выбраны и не являются краями маршрута. */
function availablePoints() {
  const fromId = Number(deliveryForm.elements.point_from_id.value);
  const toId = Number(deliveryForm.elements.point_to_id.value);
  const taken = new Set([fromId, toId, ...waypoints.map((item) => item.id)]);
  return allPoints.filter((point) => !taken.has(point.id));
}

function renderWaypointPicker() {
  const select = qs('#d-waypoint-pick');
  const options = availablePoints();
  clear(select);
  if (!options.length) {
    select.append(el('option', { value: '', text: 'Свободных точек нет' }));
    select.disabled = true;
  } else {
    select.disabled = false;
    options.forEach((point) => select.append(el('option', { value: point.id, text: point.name })));
  }
  qs('#btn-add-waypoint').disabled = !options.length;
}

function renderWaypointList() {
  const list = qs('#waypoint-list');
  clear(list);

  if (!waypoints.length) {
    list.append(el('li', { class: 'waypoints__empty', text: 'Прямой маршрут, без промежуточных точек' }));
  } else {
    waypoints.forEach((point, index) => {
      const remove = el('button', {
        class: 'btn btn--sm btn--icon',
        type: 'button',
        'aria-label': `Убрать точку ${point.name}`,
        onClick: () => {
          waypoints = waypoints.filter((item) => item.id !== point.id);
          renderWaypoints();
        },
      });
      remove.append(icon('close', { size: 14 }));

      const up = el('button', {
        class: 'btn btn--sm btn--icon',
        type: 'button',
        'aria-label': `Поднять точку ${point.name} выше`,
        disabled: index === 0,
        onClick: () => {
          const previous = waypoints[index - 1];
          waypoints[index - 1] = point;
          waypoints[index] = previous;
          renderWaypoints();
        },
      });
      up.append(icon('back', { size: 14, className: 'icon-rotate-90' }));

      list.append(
        el('li', { class: 'waypoints__item' }, [
          el('span', { class: 'waypoints__order', text: String(index + 1) }),
          el('span', { class: 'waypoints__name', text: point.name }),
          el('span', { class: 'waypoints__actions' }, [up, remove]),
        ])
      );
    });
  }
  renderWaypointPicker();
}

function renderWaypoints() {
  renderWaypointList();
}

function addWaypoint() {
  const select = qs('#d-waypoint-pick');
  const id = Number(select.value);
  if (!id) return;
  const point = allPoints.find((item) => item.id === id);
  if (!point) return;
  if (waypoints.length >= 10) {
    toast('Не больше 10 промежуточных точек в рейсе.', 'error');
    return;
  }
  waypoints.push({ id: point.id, name: point.name });
  renderWaypoints();
}

/* --------------------------- Создание рейса ------------------------------ */

function updateDeadlinePreview() {
  const preview = qs('#deadline-preview');
  const mode = deliveryForm.elements.deadline_mode.value;
  const dispatchedAt = deliveryForm.elements.dispatched_at.value;

  if (!dispatchedAt) {
    preview.textContent = '';
    return;
  }
  if (mode === 'exact') {
    const deadline = deliveryForm.elements.deadline_at.value;
    preview.textContent = deadline ? `Плановое прибытие: ${formatDateTime(deadline)}` : '';
    return;
  }

  const hours = Number(deliveryForm.elements.duration_hours.value) || 0;
  const minutes = Number(deliveryForm.elements.duration_minutes.value) || 0;
  if (hours <= 0 && minutes <= 0) {
    preview.textContent = 'Укажите время в пути.';
    return;
  }
  const deadline = new Date(new Date(dispatchedAt).getTime() + (hours * 60 + minutes) * 60000);
  preview.textContent = `Плановое прибытие: ${formatDateTime(deadline)}`;
}

function toggleDeadlineMode() {
  const isExact = deliveryForm.elements.deadline_mode.value === 'exact';
  qs('#field-hours').hidden = isExact;
  qs('#field-minutes').hidden = isExact;
  qs('#field-deadline').hidden = !isExact;
  updateDeadlinePreview();
}

function openDeliveryModal() {
  deliveryForm.reset();
  waypoints = [];
  renderWaypoints();
  deliveryForm.elements.dispatched_at.value = toLocalInputValue();
  deliveryForm.elements.duration_hours.value = '4';
  deliveryForm.elements.duration_minutes.value = '0';
  toggleDeadlineMode();
  openModal(modal);
}

async function submitDelivery(event) {
  event.preventDefault();
  const submit = qs('#delivery-submit');
  const data = Object.fromEntries(new FormData(deliveryForm).entries());

  const waypointIds = waypoints.map((item) => item.id);

  const payload = {
    point_from_id: Number(data.point_from_id),
    point_to_id: Number(data.point_to_id),
    waypoint_ids: waypointIds,
    vehicle_number: String(data.vehicle_number || '').trim(),
    dispatched_at: fromLocalInputValue(data.dispatched_at),
    comment: String(data.comment || '').trim(),
    auto_dispatch: Boolean(data.auto_dispatch),
  };

  if (!payload.point_from_id || !payload.point_to_id) {
    toast('Выберите точки отправления и прибытия.', 'error');
    return;
  }
  if (payload.point_from_id === payload.point_to_id) {
    toast('Точки отправления и прибытия должны различаться.', 'error');
    return;
  }
  if (waypointIds.some((id) => id === payload.point_from_id || id === payload.point_to_id)) {
    toast('Промежуточная точка не может совпадать с началом или концом маршрута.', 'error');
    return;
  }
  if (payload.vehicle_number.length < 3) {
    toast('Укажите корректный номер машины.', 'error');
    return;
  }

  if (data.deadline_mode === 'exact') {
    if (!data.deadline_at) {
      toast('Укажите время планового прибытия.', 'error');
      return;
    }
    payload.deadline_at = fromLocalInputValue(data.deadline_at);
  } else {
    payload.duration_hours = Number(data.duration_hours) || 0;
    payload.duration_minutes = Number(data.duration_minutes) || 0;
    if (payload.duration_hours <= 0 && payload.duration_minutes <= 0) {
      toast('Укажите время в пути.', 'error');
      return;
    }
  }

  submit.disabled = true;
  submit.textContent = 'Сохранение…';
  try {
    const delivery = await api.createDelivery(payload);
    closeModal(modal);
    toast(`Рейс #${delivery.id} создан.`, 'success');
    window.location.href = `delivery.html?id=${delivery.id}`;
  } catch (error) {
    showApiError(error);
  } finally {
    submit.disabled = false;
    submit.textContent = 'Создать рейс';
  }
}

/* -------------------------------- Запуск --------------------------------- */

(async () => {
  const user = await initLayout({ active: 'deliveries.html' });
  if (!user) return;

  const params = queryParams();
  try {
    await loadOptions();
  } catch (error) {
    toast('Не удалось загрузить справочники.', 'error');
  }
  applyFiltersToForm(params);
  state.filters = collectFilters();

  if (isAdmin()) {
    const exportBtn = qs('#btn-export');
    exportBtn.hidden = false;
    exportBtn.addEventListener('click', async () => {
      try {
        await downloadFile('/reports/export/deliveries/', state.filters, 'reisy.xlsx');
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
    loadDeliveries();
  });

  qs('#btn-reset').addEventListener('click', () => {
    setTimeout(() => {
      state.filters = {};
      state.page = 1;
      setQueryParams({});
      loadDeliveries();
    }, 0);
  });

  qs('#page-prev').addEventListener('click', () => {
    if (state.page > 1) {
      state.page -= 1;
      loadDeliveries();
    }
  });
  qs('#page-next').addEventListener('click', () => {
    if (state.page < state.pages) {
      state.page += 1;
      loadDeliveries();
    }
  });

  qs('#btn-new').addEventListener('click', openDeliveryModal);
  qs('#btn-add-waypoint').addEventListener('click', addWaypoint);
  ['point_from_id', 'point_to_id'].forEach((name) => {
    deliveryForm.elements[name].addEventListener('change', () => {
      // Точка, ставшая началом или концом маршрута, из промежуточных убирается
      const fromId = Number(deliveryForm.elements.point_from_id.value);
      const toId = Number(deliveryForm.elements.point_to_id.value);
      waypoints = waypoints.filter((item) => item.id !== fromId && item.id !== toId);
      renderWaypoints();
    });
  });
  hydrateIcons(modal);
  renderWaypoints();
  deliveryForm.addEventListener('submit', submitDelivery);
  deliveryForm.elements.deadline_mode.addEventListener('change', toggleDeadlineMode);
  ['dispatched_at', 'duration_hours', 'duration_minutes', 'deadline_at'].forEach((name) => {
    deliveryForm.elements[name].addEventListener('input', updateDeadlinePreview);
  });

  await loadDeliveries();

  if (params.new === '1') openDeliveryModal();
})();
